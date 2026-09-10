import {test} from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import os from "node:os";
import path from "node:path";
import vm from "node:vm";
import {hashNarration, hashTts, writeSidecar, matchesSidecar, sidecarPath, synthOnce} from "./tts-engines.mjs";

const source = fs.readFileSync(new URL("./build.mjs", import.meta.url), "utf8");
const ttsBlock = source.slice(source.indexOf("const ttsConf ="), source.indexOf("/* ---- 测时长"));
async function run({cached = false, legacy = false, selected = false, fail = false, mismatch = false} = {}) {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "volc-cache-test-"));
    const calls = [];
    const voice = "zh_male_liufei_uranus_bigtts";
    const scenes = ["a", "b"].map(id => ({id, narration: `narration ${id}`}));
    const manifest = {};
    try {
        for (const s of scenes) {
            if (!cached && !legacy) continue;
            const file = path.join(dir, s.id + ".mp3");
            fs.writeFileSync(file, "cached");
            manifest[s.id] = hashNarration(s.narration);
            if (!legacy) writeSidecar(file, "volc", mismatch ? "old-voice" : voice, s.narration);
        }
        fs.writeFileSync(path.join(dir, "manifest.json"), JSON.stringify(manifest));
        const context = {...fs, path, console: {log() {}, warn() {}, error() {}},
            process: {env: {}, stdout: {write() {}}, exit(code) {throw Error(`exit ${code}`);}},
            story: {meta: {tts: {provider: "volc", voice}}, scenes},
            project: {settings: {require_selected_audio: selected}}, audioDir: dir, ESTIMATE: false,
            hashNarration, writeSidecar, matchesSidecar, sidecarPath,
            synthOnce: async (engine, chosenVoice, text, out) => {
                calls.push([engine, chosenVoice, text]);
                if (fail && engine === "volc" && text.endsWith("b")) return false;
                fs.writeFileSync(out, engine);
                return true;
            }};
        await vm.runInNewContext(`(async () => {${ttsBlock}})()`, context);
        return {calls, sidecars: scenes.map(s => fs.existsSync(sidecarPath(path.join(dir, s.id + ".mp3")))
            ? JSON.parse(fs.readFileSync(sidecarPath(path.join(dir, s.id + ".mp3")))) : null)};
    } finally {fs.rmSync(dir, {recursive: true, force: true});}
}

test("matching sidecars and legacy narration manifests reuse audio", async () => {
    assert.equal((await run({cached: true})).calls.length, 0);
    assert.equal((await run({legacy: true})).calls.length, 0);
});
test("voice changes resynthesize the whole affected batch", async () => {
    const r = await run({cached: true, mismatch: true});
    assert.equal(r.calls.length, 2);
    assert.ok(r.sidecars.every(s => s.voice === "zh_male_liufei_uranus_bigtts"));
});
test("a later volc failure replaces earlier audio and sidecars with Edge", async () => {
    const r = await run({fail: true});
    assert.deepEqual(r.calls.map(c => c[0]), ["volc", "volc", "edge", "edge"]);
    assert.ok(r.sidecars.every(s => s.engine === "edge" && s.voice === "zh-CN-XiaoxiaoNeural"));
});
test("selected takes cannot be silently regenerated or downgraded", async () => {
    await assert.rejects(run({cached: true, mismatch: true, selected: true}), /take/);
});
test("cache identity includes engine, voice and narration", () => {
    const hash = hashTts("volc", "voice", "text");
    assert.equal(hash.length, 16);
    for (const args of [["edge", "voice", "text"], ["volc", "other", "text"], ["volc", "voice", "edit"]])
        assert.notEqual(hashTts(...args), hash);
});
test("empty Volc key fails immediately without a retry delay", async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "volc-empty-test-"));
    try {
        const before = Date.now();
        assert.equal(await synthOnce("volc", "voice", "text", path.join(dir, "test.mp3"), {api_key: ""}), false);
        assert.ok(Date.now() - before < 1000);
        assert.deepEqual(fs.readdirSync(dir), []);
    } finally { fs.rmSync(dir, {recursive: true, force: true}); }
});
