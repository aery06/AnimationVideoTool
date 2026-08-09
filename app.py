from pathlib import Path
import json, shutil, subprocess, sys, os, zipfile, tempfile
import gradio as gr
from engine.project_tools import FILES, write_inputs, validate, make_verification, make_manifest, export_zip

ROOT=Path(__file__).resolve().parent
DATA=ROOT/'data'
SCHEMA_BUNDLE=DATA/'schemas_v0_1.json'
BENCHMARK_BUNDLE=DATA/'benchmark_capacitor_v0_1.json'
PROJECTS=ROOT/'projects'
PROJECTS.mkdir(exist_ok=True)

LABELS={
 '01_project_input.json':'01 · Project Input',
 '02_technical_truth.json':'02 · Technical Truth',
 '03_benchmark_style.json':'03 · Benchmark Style',
 '04_storyboard.json':'04 · Storyboard',
 '05_scene_spec.json':'05 · Scene Spec',
 '06_asset_manifest.json':'06 · Asset Manifest',
 '07_narration_timing.json':'07 · Narration Timing',
 '08_render_config.json':'08 · Render Config',
 '09_verification_report.json':'09 · Verification Baseline',
}

def defaults():
    bundle=json.loads(BENCHMARK_BUNDLE.read_text(encoding='utf-8'))
    return [json.dumps(bundle[f],indent=2,ensure_ascii=False) for f in FILES]

def safe_id(texts):
    try:
        x=json.loads(texts[0]); pid=x.get('_meta',{}).get('project_id','PROJECT')
    except Exception: pid='PROJECT'
    return ''.join(c if c.isalnum() or c in '-_' else '_' for c in pid)[:80] or 'PROJECT'

def project_dir(texts):
    return PROJECTS/safe_id(texts)

def save_and_validate(*texts):
    try:
        p=project_dir(texts); p.mkdir(parents=True,exist_ok=True)
        write_inputs(p,texts)
        rep=validate(p,SCHEMA_BUNDLE)
        (p/'validation_report.json').write_text(json.dumps(rep,indent=2),encoding='utf-8')
        status='✅ VALIDATION PASSED' if rep['status']=='PASS' else '❌ VALIDATION FAILED'
        return status+'\n\n```json\n'+json.dumps(rep,indent=2)+'\n```', json.dumps(rep,indent=2)
    except Exception as e:
        return f'❌ Could not save/validate: {e}', json.dumps({'status':'FAIL','error':str(e)},indent=2)

def render_project(*texts):
    p=project_dir(texts); p.mkdir(parents=True,exist_ok=True)
    try:
        write_inputs(p,texts)
        val=validate(p,SCHEMA_BUNDLE)
        if val['status']!='PASS':
            return '❌ Render blocked: validation failed.', None, json.dumps(val,indent=2), '{}', None
        out=p/'output'; logs=p/'logs'; out.mkdir(exist_ok=True); logs.mkdir(exist_ok=True)
        env=os.environ.copy(); env['AEV_BENCH']=str(p/'input'); env['AEV_OUT']=str(out); env['AEV_LOGS']=str(logs)
        proc=subprocess.run([sys.executable,str(ROOT/'engine'/'render_engine.py')],cwd=ROOT,env=env,capture_output=True,text=True)
        (logs/'renderer_stdout.txt').write_text(proc.stdout,encoding='utf-8'); (logs/'renderer_stderr.txt').write_text(proc.stderr,encoding='utf-8')
        if proc.returncode!=0:
            return '❌ Renderer failed. Check logs in exported bundle.', None, json.dumps(val,indent=2), proc.stderr[-6000:], export_zip(p)
        pid=safe_id(texts); video=out/f'{pid}_final.mp4'
        if not video.exists():
            vids=list(out.glob('*_final.mp4')); video=vids[0] if vids else None
        if not video:
            return '❌ Renderer completed but no final MP4 found.', None, json.dumps(val,indent=2), proc.stdout[-6000:], export_zip(p)
        ver=make_verification(p,video); man=make_manifest(p,video); bundle=export_zip(p)
        status='✅ Render complete. Project workspace saved and export bundle created.'
        return status, str(video), json.dumps(ver,indent=2), json.dumps(man,indent=2), bundle
    except Exception as e:
        try: bundle=export_zip(p)
        except Exception: bundle=None
        return f'❌ Render exception: {e}', None, '{}', str(e), bundle

def export_only(*texts):
    try:
        p=project_dir(texts); p.mkdir(parents=True,exist_ok=True); write_inputs(p,texts)
        return export_zip(p), f'✅ Exported {p.name} assistant bundle.'
    except Exception as e: return None, f'❌ Export failed: {e}'

def import_bundle(file_obj):
    if not file_obj: return (*defaults(), 'No bundle selected.')
    try:
        src=Path(file_obj)
        tmp=Path(tempfile.mkdtemp(prefix='aev_import_'))
        with zipfile.ZipFile(src,'r') as z: z.extractall(tmp)
        found={}
        for f in FILES:
            matches=list(tmp.rglob(f))
            if not matches: raise FileNotFoundError(f'Missing {f}')
            found[f]=matches[0].read_text(encoding='utf-8')
        return (*[found[f] for f in FILES], '✅ Imported project bundle into editors.')
    except Exception as e:
        return (*defaults(), f'❌ Import failed: {e}')

with gr.Blocks(title='AI Electronics Video Tool · GUI MVP V0.1') as demo:
    gr.Markdown('# AI Electronics Video Tool · GUI MVP V0.1\nEdit the nine contracts, validate them, then render the benchmark pipeline. **All project state remains file-based and exportable for assistant edits.**')
    with gr.Row():
        bundle_in=gr.File(label='Import project/assistant bundle (.zip)',file_types=['.zip'])
        import_btn=gr.Button('Import Bundle')
        reset_btn=gr.Button('Load Benchmark Defaults')
    import_status=gr.Markdown('')
    editors=[]
    vals=defaults()
    for i,(fname,label) in enumerate(LABELS.items()):
        with gr.Tab(label):
            editors.append(gr.Code(value=vals[i],language='json',label=fname,lines=22))
    with gr.Row():
        validate_btn=gr.Button('Validate JSON Contracts',variant='secondary')
        start_btn=gr.Button('▶ START / RENDER',variant='primary')
        export_btn=gr.Button('Export Assistant Bundle')
    status=gr.Markdown('Ready.')
    with gr.Tab('Output Video'):
        video=gr.Video(label='Rendered MP4')
    with gr.Tab('Verification'):
        verification=gr.Code(label='Verification Report',language='json',lines=24)
    with gr.Tab('Render Manifest / Logs'):
        manifest=gr.Code(label='Render Manifest / Error',language='json',lines=24)
    bundle_out=gr.File(label='Portable project bundle for ChatGPT / backup')

    validate_btn.click(save_and_validate,inputs=editors,outputs=[status,verification])
    start_btn.click(render_project,inputs=editors,outputs=[status,video,verification,manifest,bundle_out])
    export_btn.click(export_only,inputs=editors,outputs=[bundle_out,status])
    import_btn.click(import_bundle,inputs=[bundle_in],outputs=editors+[import_status])
    reset_btn.click(lambda: (*defaults(),'✅ Benchmark defaults restored.'),outputs=editors+[import_status])

if __name__=='__main__':
    host=os.environ.get('AEV_HOST','127.0.0.1')
    port=int(os.environ.get('AEV_PORT','7860'))
    inbrowser=os.environ.get('AEV_INBROWSER','1').lower() not in {'0','false','no'}
    demo.launch(server_name=host,server_port=port,inbrowser=inbrowser,show_error=True)
