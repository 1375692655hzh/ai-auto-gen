import test from 'node:test';
import assert from 'node:assert/strict';
import {Readable} from 'node:stream';
import {mkdtempSync, readFileSync, rmSync, existsSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import pkg from 'msedge-tts';
import {synthEdge, hashNarration} from './tts-engines.mjs';

test('synthEdge collects 100ns metadata without changing audio granularity', async () => {
  const proto=pkg.MsEdgeTTS.prototype;
  const original={setMetadata:proto.setMetadata,toStream:proto.toStream,close:proto.close};
  const dir=mkdtempSync(path.join(tmpdir(),'finance-edge-test-'));
  let calls=0, closed=0;
  try {
    proto.setMetadata=async function(voice, format, options) {assert.equal(options.wordBoundaryEnabled,true);};
    proto.toStream=function(text) {
      calls++; assert.equal(text,'收入增长。');
      return {audioStream:Readable.from([Buffer.from('one whole audio')]),
        metadataStream:Readable.from([Buffer.from(JSON.stringify({Metadata:[
          {Type:'WordBoundary',Data:{Offset:1000000,Duration:4000000,text:{Text:'收入'}}},
          {Type:'WordBoundary',Data:{Offset:5000000,Duration:5000000,text:{Text:'增长'}}},
        ]}))])};
    };
    proto.close=function() {closed++;};
    const out=path.join(dir,'b1.mp3');
    await synthEdge('收入增长。','zh-CN-XiaoxiaoNeural',out);
    assert.equal(calls,1); assert.equal(closed,1);
    assert.equal(readFileSync(out,'utf8'),'one whole audio');
    assert.deepEqual(JSON.parse(readFileSync(path.join(dir,'b1.cues.json'),'utf8')),
      {origin:'provider-alignment',unit:'seconds',narrationHash:hashNarration('收入增长。'),
        cues:[{t:'收入',start:.1,end:.5},{t:'增长',start:.5,end:1}]});
    assert.ok(existsSync(out));
  } finally {
    Object.assign(proto,original);
    rmSync(dir,{recursive:true,force:true});
  }
});
