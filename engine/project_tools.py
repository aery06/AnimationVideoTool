import json, hashlib, zipfile, shutil, subprocess, sys, os
from pathlib import Path
import jsonschema

FILES = [
 '01_project_input.json','02_technical_truth.json','03_benchmark_style.json',
 '04_storyboard.json','05_scene_spec.json','06_asset_manifest.json',
 '07_narration_timing.json','08_render_config.json','09_verification_report.json'
]
SCHEMAS = [f.replace('.json','.schema.json') for f in FILES]

def load_json(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))

def sha256(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):
            h.update(b)
    return h.hexdigest()

def write_inputs(project_dir, texts):
    inp=Path(project_dir)/'input'; inp.mkdir(parents=True,exist_ok=True)
    parsed={}
    for name,text in zip(FILES,texts):
        data=json.loads(text)
        (inp/name).write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf-8')
        parsed[name]=data
    return parsed

def validate(project_dir, schema_bundle_path):
    inp=Path(project_dir)/'input'
    errors=[]; checks=[]; instances={}
    schema_bundle=load_json(schema_bundle_path)
    for f,sf in zip(FILES,SCHEMAS):
        try:
            inst=load_json(inp/f); sch=schema_bundle[sf]
            jsonschema.validate(inst,sch); instances[f]=inst
            checks.append({'check':f,'status':'PASS'})
        except Exception as e:
            errors.append(f'{f}: {e}')
            checks.append({'check':f,'status':'FAIL'})
    if errors:
        return {'status':'FAIL','checks':checks,'errors':errors}
    story=instances['04_storyboard.json']; spec=instances['05_scene_spec.json']; narr=instances['07_narration_timing.json']; assets=instances['06_asset_manifest.json']; truth=instances['02_technical_truth.json']; cfg=instances['08_render_config.json']
    story_ids=[x['scene_id'] for x in story['scenes']]; spec_ids=[x['scene_id'] for x in spec['scenes']]; narr_ids=[x['scene_id'] for x in narr['segments']]
    if not (story_ids==spec_ids==narr_ids): errors.append('Scene IDs/order mismatch across storyboard, scene spec, narration.')
    asset_ids={x['asset_id'] for x in assets['assets']}
    for sc in spec['scenes']:
        refs={sc.get('background_asset')}|{o.get('asset_id') for o in sc.get('objects',[])}
        miss=[r for r in refs if r and r not in asset_ids]
        if miss: errors.append(f"{sc['scene_id']} missing assets: {miss}")
    rule_ids={x['rule_id'] for x in truth['qa_rules']}
    for sc in spec['scenes']:
        bad=[r for r in sc.get('technical_rules',[]) if r not in rule_ids]
        if bad: errors.append(f"{sc['scene_id']} unknown technical rules: {bad}")
    if abs(story['total_duration_seconds']-cfg['video']['duration_seconds'])>1e-9: errors.append('Storyboard/render durations differ.')
    expected=int(round(cfg['video']['duration_seconds']*cfg['video']['fps']))
    if expected!=cfg['determinism']['fixed_frame_count']: errors.append('fixed_frame_count != duration*fps.')
    return {'status':'PASS' if not errors else 'FAIL','checks':checks,'errors':errors}

def probe_video(path):
    raw=subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)])
    p=json.loads(raw)
    vs=next(x for x in p['streams'] if x['codec_type']=='video')
    aud=next((x for x in p['streams'] if x['codec_type']=='audio'),None)
    return {
      'width':int(vs['width']),'height':int(vs['height']),
      'fps':vs['avg_frame_rate'],'duration_seconds':float(vs.get('duration',p['format']['duration'])),
      'frame_count':int(vs.get('nb_frames') or 0),
      'audio_sample_rate_hz': int(aud['sample_rate']) if aud else None,
      'audio_channels': int(aud['channels']) if aud else None
    }

def make_verification(project_dir, video_path):
    inp=Path(project_dir)/'input'; out=Path(project_dir)/'output'; out.mkdir(exist_ok=True)
    cfg=load_json(inp/'08_render_config.json'); baseline=load_json(inp/'09_verification_report.json')
    meta=probe_video(video_path)
    duration_err=abs(meta['duration_seconds']-cfg['video']['duration_seconds'])
    geometry=(meta['width']==cfg['video']['width'] and meta['height']==cfg['video']['height'])
    frames=(meta['frame_count']==cfg['determinism']['fixed_frame_count'])
    report={
      '_meta':{'schema_name':'verification_report','schema_version':'0.1.0','project_id':load_json(inp/'01_project_input.json').get('_meta',{}).get('project_id','PROJECT'),'status':'GUI_MVP_RENDERED'},
      'reference':baseline.get('reference',{}),
      'acceptance_thresholds':baseline.get('acceptance_thresholds',{}),
      'measured_render':{**meta,'sha256':sha256(video_path)},
      'results':{
        'generated_video_path':str(video_path),
        'duration_error_seconds':duration_err,
        'safe_zone_compliance':'NOT_MACHINE_MEASURED_IN_GUI_MVP',
        'technical_accuracy':'REQUIRES_VISION_QA',
        'storyboard_compliance':'REQUIRES_VISION_QA',
        'overall_status':'PASS_MVP_GEOMETRY' if geometry and frames and duration_err<=2 else 'FAIL_MVP_GEOMETRY'
      },
      'pass_fail':{
        'platform_geometry':'PASS' if geometry else 'FAIL',
        'fixed_frame_count':'PASS' if frames else 'FAIL',
        'duration':'PASS' if duration_err<=2 else 'FAIL',
        'full_technical_qa':'PENDING',
        'full_style_qa':'PENDING'
      },
      'known_gap':'This GUI wraps Renderer V0.1. Generic scene-action interpretation and automated vision QA remain V0.2 work.'
    }
    rp=out/'09_verification_report_actual.json'; rp.write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report

def make_manifest(project_dir, video_path):
    p=Path(project_dir); inp=p/'input'; out=p/'output'
    data={
      'project_id':load_json(inp/'01_project_input.json').get('_meta',{}).get('project_id','PROJECT'),
      'input_hashes':{f:sha256(inp/f) for f in FILES},
      'output_video':{'path':str(video_path),'sha256':sha256(video_path)},
      'gui_version':'0.1.0','renderer_version':'0.1.0'
    }
    mp=out/'render_manifest.json'; mp.write_text(json.dumps(data,indent=2),encoding='utf-8')
    return data

def export_zip(project_dir):
    p=Path(project_dir); z=p.parent/f'{p.name}_assistant_bundle.zip'
    if z.exists(): z.unlink()
    with zipfile.ZipFile(z,'w',zipfile.ZIP_DEFLATED) as zz:
        for f in p.rglob('*'):
            if f.is_file(): zz.write(f,f.relative_to(p.parent))
    return str(z)
