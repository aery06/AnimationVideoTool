#!/usr/bin/env python3
import json, math, os, subprocess, sys, hashlib, shlex, shutil
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCH = Path(os.environ.get('AEV_BENCH', Path(__file__).resolve().parents[1] / 'templates' / 'benchmark_capacitor'))
OUT = Path(os.environ.get('AEV_OUT', ROOT / 'output'))
LOGS = Path(os.environ.get('AEV_LOGS', ROOT / 'logs'))
OUT.mkdir(exist_ok=True); LOGS.mkdir(exist_ok=True)

W,H = 540,960
RENDER_FPS = 15
OUTPUT_FPS = 30
NAVY = (63, 35, 15)
GRID = (91, 60, 31)
WHITE = (245,245,245)
YELLOW = (55,220,250)
CYAN = (230,190,70)
BLUE = (220,130,50)
RED = (70,70,235)
GREEN = (80,210,100)
GREY = (160,160,160)
DARK = (25,25,25)
FONT = cv2.FONT_HERSHEY_SIMPLEX

def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def ease(t):
    t=max(0,min(1,t)); return 3*t*t-2*t*t*t

def draw_grid(img, step=36):
    img[:] = NAVY
    for x in range(0,W,step): cv2.line(img,(x,0),(x,H),GRID,1,cv2.LINE_AA)
    for y in range(0,H,step): cv2.line(img,(0,y),(W,y),GRID,1,cv2.LINE_AA)
    for x in range(0,W,step*5): cv2.line(img,(x,0),(x,H),(105,70,35),1,cv2.LINE_AA)
    for y in range(0,H,step*5): cv2.line(img,(0,y),(W,y),(105,70,35),1,cv2.LINE_AA)

def hex_bgr(value, fallback=NAVY):
    value=str(value or '').strip().lstrip('#')
    if len(value)==3: value=''.join(c*2 for c in value)
    try: return (int(value[4:6],16),int(value[2:4],16),int(value[0:2],16))
    except Exception: return fallback

def resize_cover(frame):
    if frame is None or frame.size==0: return None
    h,w=frame.shape[:2]; scale=max(W/max(w,1),H/max(h,1)); nw,nh=max(W,int(round(w*scale))),max(H,int(round(h*scale)))
    resized=cv2.resize(frame,(nw,nh),interpolation=cv2.INTER_AREA if scale<1 else cv2.INTER_LINEAR)
    x=max(0,(nw-W)//2); y=max(0,(nh-H)//2)
    return resized[y:y+H,x:x+W]

class BackgroundProvider:
    def __init__(self, bench, manifest):
        self.root=Path(bench)/'assets'; self.content_root=Path(bench)/'scene_images'; self.assets={a['asset_id']:a for a in manifest.get('assets',[])}; self.images={}; self.raw_images={}; self.videos={}; self.video_frames={}; self.generated={}

    def _image(self, path):
        key=str(path)
        if key not in self.images: self.images[key]=resize_cover(cv2.imread(key,cv2.IMREAD_COLOR))
        return self.images[key]

    def _video(self, path, seconds):
        key=str(path); cap=self.videos.get(key)
        if cap is None:
            cap=cv2.VideoCapture(key); self.videos[key]=cap
        if not cap.isOpened(): return None
        fps=cap.get(cv2.CAP_PROP_FPS) or 30.0; count=int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0); duration=count/fps if count>0 else 0
        position=(seconds%duration) if duration>0 else max(0,seconds); target=max(0,int(position*fps))
        previous=self.video_frames.get(key)
        if previous and previous[0]==target: return previous[1]
        if not previous or target!=previous[0]+1: cap.set(cv2.CAP_PROP_POS_FRAMES,target)
        ok,frame=cap.read()
        if not ok and target:
            cap.set(cv2.CAP_PROP_POS_FRAMES,0); ok,frame=cap.read(); target=0
        fitted=resize_cover(frame) if ok else None
        if fitted is not None: self.video_frames[key]=(target,fitted)
        return fitted

    def __del__(self):
        for cap in self.videos.values(): cap.release()

    def draw(self, img, asset_id, seconds):
        asset=self.assets.get(asset_id,{"source_type":"built_in_grid","source_value":"engineering_grid"})
        source_type=asset.get('source_type','built_in_grid'); value=asset.get('source_value','engineering_grid')
        if source_type=='solid_color': img[:]=hex_bgr(value); return
        if source_type=='gradient':
            key=('gradient',str(value))
            if key not in self.generated:
                colors=[x.strip() for x in str(value).split(',')]; top=np.array(hex_bgr(colors[0] if colors else ''),dtype=np.float32); bottom=np.array(hex_bgr(colors[1] if len(colors)>1 else ''),dtype=np.float32)
                blend=np.linspace(0,1,H,dtype=np.float32)[:,None,None]; self.generated[key]=np.repeat((top*(1-blend)+bottom*blend).astype(np.uint8),W,axis=1)
            img[:]=self.generated[key]; return
        if source_type in {'external_image','external_video'}:
            path=self.root/Path(str(value)).name
            frame=self._image(path) if source_type=='external_image' else self._video(path,seconds)
            if frame is not None: img[:]=frame; return
        draw_grid(img)

    def draw_content(self, img, asset_id, progress, fit='contain', motion='none'):
        if not asset_id: return False
        asset=self.assets.get(asset_id)
        if not asset or asset.get('source_type')!='content_image': return False
        path=self.content_root/Path(str(asset.get('source_value',''))).name; key=str(path)
        if key not in self.raw_images: self.raw_images[key]=cv2.imread(key,cv2.IMREAD_COLOR)
        source=self.raw_images[key]
        if source is None or source.size==0: return False
        h,w=source.shape[:2]; base=max(W/w,H/h) if fit=='cover' else min(W/w,H/h); zoom=1.0+(0.08*max(0,min(1,progress)) if motion=='slow_zoom' else 0)
        scale=base*zoom; nw,nh=max(1,int(round(w*scale))),max(1,int(round(h*scale))); resized=cv2.resize(source,(nw,nh),interpolation=cv2.INTER_AREA if scale<1 else cv2.INTER_LINEAR)
        if fit=='cover' or nw>W or nh>H:
            x=max(0,(nw-W)//2); y=max(0,(nh-H)//2); crop=resized[y:y+min(H,nh),x:x+min(W,nw)]
            oy=(H-crop.shape[0])//2; ox=(W-crop.shape[1])//2; img[oy:oy+crop.shape[0],ox:ox+crop.shape[1]]=crop
        else:
            x=(W-nw)//2; y=(H-nh)//2; cv2.rectangle(img,(max(0,x-3),max(0,y-3)),(min(W-1,x+nw+2),min(H-1,y+nh+2)),(230,230,230),2,cv2.LINE_AA); img[y:y+nh,x:x+nw]=resized
        return True

def put_center(img,text,y,size=0.8,color=WHITE,th=2):
    (tw,_),_ = cv2.getTextSize(text,FONT,size,th)
    cv2.putText(img,text,((W-tw)//2,int(y)),FONT,size,color,th,cv2.LINE_AA)

def wrap_words(text,max_words=6):
    words=text.upper().split(); return [' '.join(words[i:i+max_words]) for i in range(0,len(words),max_words)]

def draw_caption(img,text,scene_t,scene_d):
    if not str(text or '').strip(): return
    chunks=wrap_words(text,6)
    idx=min(len(chunks)-1,int((scene_t/max(scene_d,0.001))*len(chunks)))
    cap=chunks[idx]; y=775
    (tw,_),_=cv2.getTextSize(cap,FONT,0.55,2); x=max(48,(W-tw)//2)
    cv2.rectangle(img,(max(28,x-12),y-34),(min(W-28,x+tw+12),y+12),(14,20,28),-1)
    cv2.putText(img,cap,(x,y),FONT,0.55,WHITE,2,cv2.LINE_AA)

def draw_capacitor(img,cx,cy,s=1.0,cutaway=False,polarity=False,label=False):
    bw=int(92*s); bh=int(185*s); x1,y1=cx-bw//2,cy-bh//2; x2,y2=cx+bw//2,cy+bh//2
    cv2.ellipse(img,(cx,y1+8),(bw//2,16),0,180,360,(210,210,215),-1,cv2.LINE_AA)
    cv2.rectangle(img,(x1,y1+8),(x2,y2-10),(190,190,198),-1)
    cv2.rectangle(img,(x1+8,y1+14),(x2-8,y2-18),(115,120,130),-1)
    cv2.ellipse(img,(cx,y2-10),(bw//2,13),0,0,180,(95,100,110),-1,cv2.LINE_AA)
    cv2.line(img,(cx-18,y2),(cx-18,y2+70),WHITE,max(2,int(4*s)),cv2.LINE_AA)
    cv2.line(img,(cx+18,y2),(cx+18,y2+70),WHITE,max(2,int(4*s)),cv2.LINE_AA)
    if polarity:
        cv2.rectangle(img,(x2-18,y1+22),(x2-8,y2-20),WHITE,-1); cv2.putText(img,'-',(x2-18,y1+52),FONT,0.45,DARK,2,cv2.LINE_AA)
    if label:
        cv2.putText(img,'25V',(x1+14,cy-10),FONT,0.50,WHITE,2,cv2.LINE_AA); cv2.putText(img,'100uF',(x1+7,cy+18),FONT,0.42,WHITE,1,cv2.LINE_AA)
    if cutaway:
        cv2.rectangle(img,(cx-24,y1+32),(cx-11,y2-35),YELLOW,-1); cv2.rectangle(img,(cx+11,y1+32),(cx+24,y2-35),CYAN,-1); cv2.rectangle(img,(cx-8,y1+32),(cx+8,y2-35),(230,225,190),-1)

def draw_battery(img,cx,cy,s=1.0):
    w,h=int(70*s),int(135*s)
    cv2.rectangle(img,(cx-w//2,cy-h//2),(cx+w//2,cy+h//2),(55,55,65),-1); cv2.rectangle(img,(cx-16,cy-h//2-12),(cx+16,cy-h//2),(185,185,195),-1)
    cv2.putText(img,'+',(cx-10,cy-h//4),FONT,0.7,WHITE,2,cv2.LINE_AA); cv2.putText(img,'-',(cx-9,cy+h//4),FONT,0.8,WHITE,2,cv2.LINE_AA)

def draw_lamp(img,cx,cy,s=1.0,on=False):
    r=int(35*s)
    if on:
        for rr in range(r+28,r,-6): cv2.circle(img,(cx,cy),rr,(40,80+rr,120+rr),1,cv2.LINE_AA)
    cv2.circle(img,(cx,cy),r,(120,180,222),3,cv2.LINE_AA); cv2.line(img,(cx-r//2,cy-r//2),(cx+r//2,cy+r//2),WHITE,2,cv2.LINE_AA); cv2.line(img,(cx+r//2,cy-r//2),(cx-r//2,cy+r//2),WHITE,2,cv2.LINE_AA)

def arrow(img,p1,p2,color=YELLOW,th=4): cv2.arrowedLine(img,p1,p2,color,th,cv2.LINE_AA,tipLength=0.14)

def draw_wave(img,x0,y0,w,h,mode='dip',progress=1.0,color=YELLOW):
    pts=[]; n=130; maxn=max(2,int(n*max(0,min(1,progress))))
    for i in range(maxn):
        t=i/(n-1); x=x0+int(t*w)
        if mode=='dip':
            y=y0 + int(0.02*h*math.sin(t*16));
            if 0.45<t<0.62: y += int(h*(1-abs(t-0.535)/0.085)*0.75)
        elif mode=='smooth':
            y=y0 + int(0.02*h*math.sin(t*16));
            if 0.47<t<0.59: y += int(h*(1-abs(t-0.53)/0.06)*0.28)
        elif mode=='mixed': y=y0 + int(math.sin(t*18)*h*0.23 + math.sin(t*70)*h*0.08)
        else: y=y0 + int(math.sin(t*18)*h*0.22)
        pts.append((x,y))
    if len(pts)>1: cv2.polylines(img,[np.array(pts,np.int32)],False,color,3,cv2.LINE_AA)

def draw_pipe(img,cx,cy,s=1.0,flow=1.0,valve_angle=0,tank=None):
    x1,x2=int(cx-190*s),int(cx+190*s); y=int(cy)
    cv2.line(img,(x1,y),(x2,y),(190,190,195),int(34*s),cv2.LINE_AA); cv2.line(img,(x1,y),(x2,y),(70,155,235),int(22*s),cv2.LINE_AA)
    vx=int(cx-70*s); cv2.circle(img,(vx,y),int(28*s),(175,175,180),4,cv2.LINE_AA)
    ang=math.radians(valve_angle); dx=int(math.cos(ang)*25*s); dy=int(math.sin(ang)*25*s); cv2.line(img,(vx-dx,y-dy),(vx+dx,y+dy),YELLOW,6,cv2.LINE_AA)
    if flow>0.02:
        for i in range(6):
            xx=int(x1+((i/6 + flow*0.7)%1.0)*(x2-x1)); arrow(img,(xx-18,y),(xx+14,y),CYAN,2)
    if tank is not None:
        tx,ty,level=tank; tw,th=int(105*s),int(155*s)
        cv2.rectangle(img,(tx-tw//2,ty-th//2),(tx+tw//2,ty+th//2),WHITE,3,cv2.LINE_AA)
        fill_h=int((th-8)*max(0,min(1,level))); cv2.rectangle(img,(tx-tw//2+4,ty+th//2-4-fill_h),(tx+tw//2-4,ty+th//2-4),(70,155,235),-1)
        cv2.line(img,(tx,ty+th//2),(tx,y),WHITE,12,cv2.LINE_AA); cv2.line(img,(tx,ty+th//2),(tx,y),(70,155,235),7,cv2.LINE_AA)

def draw_scene(scene, global_t, narration, backgrounds=None):
    img=np.zeros((H,W,3),dtype=np.uint8); sid=scene['scene_id']; t=global_t-scene['start_seconds']; d=scene['duration_seconds']; p=max(0,min(1,t/d))
    if backgrounds: backgrounds.draw(img,scene.get('background_asset'),t)
    else: draw_grid(img)
    has_content=backgrounds.draw_content(img,scene.get('content_image_asset'),p,scene.get('image_fit','contain'),scene.get('image_motion','none')) if backgrounds else False
    if has_content: pass
    elif sid=='S01':
        s=0.82+0.18*ease(min(1,t/0.7)); draw_capacitor(img,W//2,500,s); put_center(img,'CAPACITOR',230,0.95,YELLOW,2)
        if t>2.0:
            for i in range(8):
                a=2*math.pi*i/8+t*0.35; rr=90+int(9*math.sin(t*2+i)); cv2.circle(img,(W//2+int(math.cos(a)*rr),500+int(math.sin(a)*rr)),5,YELLOW,-1,cv2.LINE_AA)
            put_center(img,'TEMPORARY ENERGY STORAGE',680,0.55,WHITE,2)
    elif sid=='S02':
        draw_battery(img,100,500,0.8); draw_lamp(img,438,500,0.9,on=t>3.5); draw_capacitor(img,270,500,0.95,cutaway=True)
        if t>0.7:
            n=max(1,int(5*min(1,(t-0.7)/2.3)))
            for i in range(n):
                yy=440+i*28; cv2.circle(img,(246,yy),5,RED,-1); cv2.circle(img,(294,yy),5,BLUE,-1)
            put_center(img,'STORE',250,0.75,YELLOW,2)
        if t>3.3: arrow(img,(325,500),(397,500),YELLOW,4); put_center(img,'RELEASE',735,0.72,YELLOW,2)
    elif sid=='S03':
        cv2.line(img,(72,380),(470,380),GREY,1); cv2.line(img,(72,660),(470,660),GREY,1); draw_wave(img,80,380,380,120,'dip',min(1,t/2.5),RED); draw_wave(img,80,660,380,120,'smooth',min(1,max(0,t-2.0)/3.0),GREEN)
        put_center(img,'WITHOUT LOCAL STORAGE',245,0.48,WHITE,1)
        if t>2.2: put_center(img,'REDUCED VOLTAGE DIP',525,0.55,YELLOW,2)
    elif sid=='S04':
        draw_wave(img,42,490,150,130,'mixed',min(1,t/1.6),WHITE); cv2.line(img,(255,430),(255,550),YELLOW,5); cv2.line(img,(280,430),(280,550),YELLOW,5); arrow(img,(200,490),(242,490),CYAN,3); arrow(img,(292,490),(340,490),CYAN,3); draw_wave(img,345,490,150,130,'filtered',min(1,max(0,t-2.2)/2.5),GREEN); put_center(img,'FILTER',270,0.8,YELLOW,2)
    elif sid=='S05': draw_pipe(img,270,520,0.95,flow=(t*0.28)%1.0,valve_angle=0); put_center(img,'WATER FLOW',270,0.75,YELLOW,2); put_center(img,'ANALOGY',710,0.48,WHITE,1)
    elif sid=='S06':
        if t<2.0:
            ang=90*ease(min(1,t/1.2)); flow=max(0,1-ease(min(1,max(0,t-0.7)/1.0))); draw_pipe(img,270,590,0.9,flow=flow,valve_angle=ang); put_center(img,'VALVE CLOSES',260,0.58,YELLOW,2)
        else:
            level=min(0.85,0.1+0.75*ease(min(1,(t-2.7)/3.8))); draw_pipe(img,270,620,0.9,flow=(t*0.25)%1.0,valve_angle=0,tank=(300,410,level)); put_center(img,'ADD A STORAGE TANK',230,0.58,WHITE,2)
            if t>3.8: put_center(img,'RESERVE',760,0.70,YELLOW,2)
    elif sid=='S07':
        drain=ease(min(1,max(0,t-0.8)/5.8)); level=0.85-0.73*drain; draw_pipe(img,270,620,0.9,flow=(t*0.22)%1.0 if t<6.2 else 0.0,valve_angle=90,tank=(300,410,level)); put_center(img,'FLOW CONTINUES BRIEFLY',235,0.54,YELLOW,2); cv2.putText(img,f'RESERVE {int(level*100):02d}%',(190,735),FONT,0.55,WHITE,2,cv2.LINE_AA)
    elif sid=='S08':
        level=max(0.15,0.75-0.25*p); draw_pipe(img,160,610,0.48,flow=0,valve_angle=90,tank=(160,455,level)); draw_capacitor(img,385,500,0.90); arrow(img,(235,500),(325,500),YELLOW,4); put_center(img,'ANALOGY  ->  ELECTRICAL MODEL',250,0.50,WHITE,1); put_center(img,'TEMPORARY ENERGY STORAGE',735,0.53,YELLOW,2)
    elif sid=='S09':
        draw_capacitor(img,250,500,1.22,label=True); cv2.rectangle(img,(360,390),(410,650),WHITE,2); level=min(1.0,max(0,(t-1.2)/3.1)); yy=int(645-level*250); color=GREEN if level<0.72 else YELLOW; cv2.rectangle(img,(365,yy),(405,645),color,-1); cv2.line(img,(350,470),(420,470),RED,3); cv2.putText(img,'25V RATING',(335,450),FONT,0.38,WHITE,1,cv2.LINE_AA); put_center(img,'MAXIMUM RATED VOLTAGE',245,0.52,YELLOW,2)
    elif sid=='S10':
        draw_capacitor(img,235,500,1.15,polarity=True,label=True); cv2.putText(img,'+',(370,455),FONT,1.2,GREEN,3,cv2.LINE_AA); cv2.putText(img,'-',(370,545),FONT,1.4,RED,3,cv2.LINE_AA); put_center(img,'CHECK VOLTAGE + POLARITY',245,0.55,YELLOW,2)
        if t>2.3: cv2.rectangle(img,(112,690),(428,760),(30,55,75),-1); cv2.rectangle(img,(112,690),(428,760),YELLOW,2); put_center(img,'RESPECT COMPONENT LIMITS',735,0.48,WHITE,1)
    draw_caption(img,narration,t,d); return img

def _tts_binary():
    explicit=os.environ.get('AEV_TTS_CMD')
    if explicit: return explicit
    for candidate in ('espeak-ng','espeak'):
        found=shutil.which(candidate)
        if found: return found
    raise RuntimeError('No local TTS executable found. Install eSpeak NG/eSpeak or set AEV_TTS_CMD.')

def resolve_voice(audio_config):
    voice_type=audio_config.get('voice_type','female')
    voices={'male':'en-us+m3','female':'en-us+f3','robotic':'en-us+croak'}
    if voice_type=='custom': return audio_config.get('custom_voice') or 'en-us'
    return voices.get(voice_type,'en-us+f3')

def validate_voice(tts, voice):
    """Fail early with an actionable error when eSpeak cannot resolve a voice."""
    check=subprocess.run([tts,'-q','-v',voice,'Voice validation'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
    if check.returncode:
        detail=check.stderr.strip()
        raise ValueError(
            f'Invalid custom voice {voice!r}. Use an installed eSpeak voice such as '
            f'en-us, en-us+m3, en-us+f3, or en-us+croak. '
            f'Run `espeak-ng --voices` to see installed base voices.'
            + (f' eSpeak said: {detail}' if detail else '')
        )

def make_audio(storyboard, outwav, audio_config):
    tmp=OUT/'audio_scenes'; tmp.mkdir(exist_ok=True); concat=[]; tts=_tts_binary()
    voice=resolve_voice(audio_config); validate_voice(tts,voice)
    for scene in storyboard['scenes']:
        sid=scene['scene_id']; text=scene['narration_draft']; dur=scene['duration_seconds']; raw=tmp/f'{sid}_raw.wav'; fixed=tmp/f'{sid}.wav'
        subprocess.run([tts,'-s','165','-v',voice,'-w',str(raw),text],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        subprocess.run(['ffmpeg','-y','-loglevel','error','-i',str(raw),'-af',f'apad,atrim=0:{dur},aresample=48000','-ac','2',str(fixed)],check=True); concat.append(f"file '{fixed.as_posix()}'")
    listfile=tmp/'concat.txt'; listfile.write_text('\n'.join(concat),encoding='utf-8'); subprocess.run(['ffmpeg','-y','-loglevel','error','-f','concat','-safe','0','-i',str(listfile),'-t',str(storyboard['total_duration_seconds']),'-ar','48000','-ac','2',str(outwav)],check=True)

def prepare_uploaded_audio(source, outwav, duration):
    if not Path(source).is_file(): raise FileNotFoundError(f'Uploaded audio not found: {source}')
    audio_filter=f'apad,atrim=0:{duration},aresample=48000'
    subprocess.run(['ffmpeg','-y','-loglevel','error','-i',str(source),'-vn','-af',audio_filter,'-ar','48000','-ac','2',str(outwav)],check=True)

def render(bench=DEFAULT_BENCH, suffix=''):
    storyboard=load_json(bench/'04_storyboard.json'); spec=load_json(bench/'05_scene_spec.json'); cfg=load_json(bench/'08_render_config.json')
    asset_manifest=load_json(bench/'06_asset_manifest.json'); backgrounds=BackgroundProvider(bench,asset_manifest)
    audio_config=cfg.get('audio',{}); uploaded_audio=os.environ.get('AEV_AUDIO_FILE')
    # Validate generated voices before spending time rendering video frames.
    if not uploaded_audio:
        tts=_tts_binary(); validate_voice(tts,resolve_voice(audio_config))
    narration_map={s['scene_id']:s['narration_draft'] for s in storyboard['scenes']}; total=cfg['video']['duration_seconds']; total_frames=int(round(total*RENDER_FPS)); pid=load_json(bench/'01_project_input.json').get('_meta',{}).get('project_id','PROJECT')
    silent=OUT/f'{pid}_silent{suffix}.mp4'; audio=OUT/f'{pid}_narration{suffix}.wav'; final=OUT/f'{pid}_final{suffix}.mp4'
    cmd=['ffmpeg','-y','-loglevel','error','-f','rawvideo','-pix_fmt','bgr24','-s',f'{W}x{H}','-r',str(RENDER_FPS),'-i','-','-vf',f'scale={cfg["video"]["width"]}:{cfg["video"]["height"]}:flags=lanczos,fps={cfg["video"]["fps"]}','-frames:v',str(cfg['determinism']['fixed_frame_count']),'-an','-c:v','libx264','-preset','veryfast','-crf','20','-pix_fmt','yuv420p','-movflags','+faststart',str(silent)]
    proc=subprocess.Popen(cmd,stdin=subprocess.PIPE); scenes=spec['scenes']; si=0; midframes=[]
    for fi in range(total_frames):
        gt=fi/RENDER_FPS
        while si < len(scenes)-1 and gt >= scenes[si]['end_seconds']-1e-9: si+=1
        scene=scenes[si]; img=draw_scene(scene,gt,narration_map[scene['scene_id']],backgrounds); proc.stdin.write(img.tobytes()); mid=scene['start_seconds']+scene['duration_seconds']/2
        if abs(gt-mid)<1/(2*RENDER_FPS):
            p=OUT/f'{scene["scene_id"]}_mid.png'; cv2.imwrite(str(p),img); midframes.append(str(p))
    proc.stdin.close(); rc=proc.wait()
    if rc!=0: raise RuntimeError('ffmpeg video render failed')
    if uploaded_audio: prepare_uploaded_audio(uploaded_audio,audio,total)
    else: make_audio(storyboard,audio,audio_config)
    volume=max(0,float(audio_config.get('volume',1.0)))
    subprocess.run(['ffmpeg','-y','-loglevel','error','-i',str(silent),'-i',str(audio),'-c:v','copy','-af',f'volume={volume}','-c:a','aac','-b:a','160k','-t',str(total),str(final)],check=True)
    return final, midframes

def sha256(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()

if __name__=='__main__':
    final, frames=render(); print(final); print('sha256',sha256(final)); print('midframes',len(frames))
