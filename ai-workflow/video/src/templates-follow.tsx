// Built-in deterministic SVG and collage shots. No external renderer or API.
// 拼贴快切取舍：父 beat 保持单 Scene + 单 audio，内部按 visualShots 切 3–6s 构图。
// 不拆成多个 Remotion Sequence——拆段会改 scene id（触发重合成）或需要 audio offset。
// 多 shot 复用同一张已生成拼贴图的不同安全构图 + 独立文字卡；不伪称图内元素分层。
import React from 'react';
import {AbsoluteFill, Img, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import type {SceneProps, CaptionCue} from './story-types';
import {captionAt, splitCaption, visualShots} from '../shared/captions.mjs';
import {FONT} from './ui';

const Subtitle: React.FC<{text: string}> = ({text}) => text ? <div style={{position:'absolute', bottom:44, left:80, right:80, textAlign:'center'}}><span style={{display:'inline-block', whiteSpace:'pre-wrap', maxWidth:1400, padding:'14px 30px', background:'#201e1be8', color:'#fff', borderRadius:12, fontSize:40, lineHeight:1.4}}>{text}</span></div> : null;
const cuesOf = (caption: SceneProps['caption']): CaptionCue[] => Array.isArray(caption) ? caption : [];
const clamp = (x: number) => Math.max(0, Math.min(1,x));

export const VoxFastCutTpl: React.FC<SceneProps> = ({scene, duration, caption}) => {
  const frame = useCurrentFrame(), {fps} = useVideoConfig();
  const shots = visualShots(cuesOf(caption), duration, fps);
  const index = Math.max(0, shots.findIndex(s => frame >= s.start && frame < s.end));
  const shot = shots[index], phase = index % 3;
  const data = scene.data as {image?: string; labels?: string[]; fallback_title?: string};
  const labels = data.labels || [];
  const label = labels[index] || splitCaption(shot.label)[0] || data.fallback_title || '';
  return <AbsoluteFill style={{background:'#e8dec7', color:'#30291f', fontFamily:FONT, overflow:'hidden'}}>
    <div style={{position:'absolute', top:36, left:70, fontSize:25, letterSpacing:4}}>VOX · {String(index+1).padStart(2,'0')}</div>
    {/* Reposition the complete raster: never pretend its internal elements are layers. */}
    <div style={{position:'absolute', left:phase===1 ? 680 : 80, top:100, width:phase===2 ? 1120 : 1060, height:710, padding:16, background:'#fffdf6', boxShadow:'8px 14px 0 #76695240', transform:`rotate(${phase===1?1:-1}deg)`}}>
      {data.image ? <Img src={staticFile(data.image)} style={{width:'100%',height:'100%',objectFit:'contain'}}/> : <div style={{fontSize:66,padding:80}}>{data.fallback_title}</div>}
    </div>
    <div style={{position:'absolute',left:phase===1?90:1260,top:phase===2?350:220,width:phase===1?490:540, padding:'30px 20px',borderTop:'10px solid #b3352c',background:'#fffaf0',fontSize:46,lineHeight:1.5,whiteSpace:'pre-wrap',transform:`translateY(${(1-clamp((frame-shot.start)/(fps*.3)))*22}px)`}}>{label}</div>
    <Subtitle text={captionAt(caption,frame,duration,fps)}/>
  </AbsoluteFill>;
};

export const HandDrawnTpl: React.FC<SceneProps> = ({scene, duration, caption}) => {
  const frame = useCurrentFrame(), {fps} = useVideoConfig();
  const cues = cuesOf(caption);
  const shots = visualShots(cues, duration, fps);
  const page = Math.max(0, shots.findIndex(s => frame >= s.start && frame < s.end));
  const shot = shots[page];
  const data = scene.data as {labels?: string[]};
  // Only literal phrases from narration/on_screen; arrows show reading order, not inferred causality.
  const phrase = splitCaption(shot.label || scene.narration);
  const labels = phrase.slice(0,3).map(s => s.replace(/\n/g,''));
  if (!labels.length) labels.push(...(data.labels || []).slice(0,3));
  return <AbsoluteFill style={{background:'#fffdf7',color:'#263440',fontFamily:FONT}}>
    <div style={{position:'absolute',top:45,left:90,fontSize:28,color:'#65716f'}}>手绘跟随 · 原文顺序 {page+1}/{shots.length}</div>
    <svg viewBox="0 0 1920 1080" width="1920" height="1080" style={{position:'absolute'}}>
      {labels.map((label,i) => {
        const matching = cues.find(c => c.start>=shot.start && c.start<shot.end && label.includes(c.t.replace(/\n/g,'')));
        const start = matching?.start ?? shot.start + i*(shot.end-shot.start)/Math.max(1,labels.length);
        const draw = clamp((frame-start)/(fps*.7)), x = 115+i*595;
        return <g key={`${page}-${i}`} opacity={frame>=start?1:0}>
          <path d={`M ${x+12} 255 Q ${x-6} 260 ${x} 280 L ${x+3} 650 Q ${x+1} 670 ${x+20} 667 L ${x+500} 670 Q ${x+520} 664 ${x+518} 645 L ${x+515} 275 Q ${x+510} 253 ${x+490} 257 Z`} fill="none" stroke="#263440" strokeWidth="5" pathLength="1" strokeDasharray="1" strokeDashoffset={1-draw}/>
          <foreignObject x={x+30} y="320" width="460" height="310"><div style={{fontSize:42,lineHeight:1.55,overflowWrap:'break-word',opacity:clamp(draw*2)}}>{label}</div></foreignObject>
          <path d={`M ${x+35} 615 Q ${x+220} 608 ${x+465} 615`} fill="none" stroke="#d45b3d" strokeWidth="8" pathLength="1" strokeDasharray="1" strokeDashoffset={1-clamp((draw-.5)*2)}/>
          {i>0 ? <path d={`M ${x-65} 460 L ${x-15} 460 M ${x-29} 445 L ${x-13} 460 L ${x-29} 475`} fill="none" stroke="#d45b3d" strokeWidth="5" pathLength="1" strokeDasharray="1" strokeDashoffset={1-draw}/> : null}
        </g>;
      })}
    </svg>
    <Subtitle text={captionAt(caption,frame,duration,fps)}/>
  </AbsoluteFill>;
};
