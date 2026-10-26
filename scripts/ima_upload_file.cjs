#!/usr/bin/env node
'use strict';
/**
 * ima_upload_file.cjs — 单文件上传到 ima 知识库根目录(六步流程, 2026-10-26)。
 *
 * 从 workbuddy 老项目 ima-uploader.cjs 裁剪: 去掉文件夹/改名逻辑(文件名由调用方
 * 完全控制且唯一), 保留 GATE 纪律: preflight → check_repeated_names → create_media
 * → cos-upload → add_knowledge(title=file_name 铁律)。
 *
 * 用法: node ima_upload_file.cjs <file_abs_path> <kb_id>
 * 回包: JSON {success, media_id?, error?} (stdout)
 */
const fs = require('fs');
const path = require('path');
const os = require('os');
const { execFileSync } = require('child_process');

const SKILL_DIR = path.join(os.homedir(), '.agents', 'skills', 'ima-skill');
const SCRIPTS = path.join(SKILL_DIR, 'knowledge-base', 'scripts');

function cred() {
  return {
    clientId: fs.readFileSync(path.join(os.homedir(), '.config/ima/client_id'), 'utf8').trim(),
    apiKey: fs.readFileSync(path.join(os.homedir(), '.config/ima/api_key'), 'utf8').trim(),
  };
}

async function main() {
  const [filePath, kbId] = process.argv.slice(2);
  if (!filePath || !kbId) {
    console.log(JSON.stringify({ success: false, error: 'usage: ima_upload_file.cjs <file> <kb_id>' }));
    process.exit(1);
  }
  const { imaApi } = require(path.join(SKILL_DIR, 'ima_api.cjs'));
  const c = cred();

  // Step 1: preflight (GATE 1)
  let pre;
  try {
    pre = JSON.parse(execFileSync('node', [path.join(SCRIPTS, 'preflight-check.cjs'),
                                           '--file', filePath],
                                  { encoding: 'utf8', timeout: 30000 }).trim());
  } catch (err) {
    const stdout = err.stdout ? err.stdout.toString().trim() : '';
    if (stdout) { try { pre = JSON.parse(stdout); } catch (e) { /* fallthrough */ } }
  }
  if (!pre || pre.pass === false) {
    console.log(JSON.stringify({ success: false,
      error: 'preflight_rejected: ' + ((pre && pre.reason) || 'no output') }));
    process.exit(2);
  }
  const fileName = pre.file_name;
  const { file_ext, file_size, media_type, content_type } = pre;

  // Step 2: check_repeated_names (GATE 3)
  const checkResp = JSON.parse(await imaApi('openapi/wiki/v1/check_repeated_names', {
    params: [{ name: fileName, media_type: media_type }],
    knowledge_base_id: kbId,
  }, c));
  if (checkResp.code !== 0) {
    console.log(JSON.stringify({ success: false, error: 'check_repeated_failed: ' + checkResp.msg }));
    process.exit(3);
  }
  const reps = (checkResp.data && checkResp.data.is_repeated_list) || [];
  if (reps.some((r) => r.is_repeated)) {
    console.log(JSON.stringify({ success: false, error: 'repeated_name', repeated: true }));
    process.exit(4);                       // 同名=大概率已传过, 调用方记 done 跳过
  }

  // Step 3: create_media
  const createResp = JSON.parse(await imaApi('openapi/wiki/v1/create_media', {
    file_name: fileName, file_size: file_size, content_type: content_type,
    knowledge_base_id: kbId, file_ext: file_ext,
  }, c));
  if (createResp.code !== 0) {
    console.log(JSON.stringify({ success: false, error: 'create_media_failed: ' + createResp.msg }));
    process.exit(5);
  }
  const mediaId = createResp.data.media_id;
  const cos = createResp.data.cos_credential;
  if (!cos) {
    console.log(JSON.stringify({ success: false, error: 'no cos_credential' }));
    process.exit(6);
  }

  // Step 4: cos-upload (GATE 4)
  try {
    execFileSync('node', [path.join(SCRIPTS, 'cos-upload.cjs'),
      '--file', filePath,
      '--secret-id', cos.secret_id, '--secret-key', cos.secret_key,
      '--token', cos.token, '--bucket', cos.bucket_name, '--region', cos.region,
      '--cos-key', cos.cos_key, '--content-type', content_type,
      '--start-time', String(cos.start_time), '--expired-time', String(cos.expired_time),
      '--timeout', '300000'], { encoding: 'utf8', timeout: 330000, stdio: 'pipe' });
  } catch (err) {
    const stderr = err.stderr ? err.stderr.toString().trim() : '';
    console.log(JSON.stringify({ success: false,
      error: 'cos_upload_failed: ' + (stderr || err.message).slice(0, 160) }));
    process.exit(7);
  }

  // Step 5: add_knowledge (GATE 2: title = file_name)
  const addResp = JSON.parse(await imaApi('openapi/wiki/v1/add_knowledge', {
    media_type: media_type, media_id: mediaId, title: fileName,
    knowledge_base_id: kbId,
    file_info: { cos_key: cos.cos_key, file_size: file_size, file_name: fileName },
  }, c));
  if (addResp.code !== 0) {
    console.log(JSON.stringify({ success: false, error: 'add_knowledge_failed: ' + addResp.msg }));
    process.exit(8);
  }
  console.log(JSON.stringify({ success: true,
    media_id: (addResp.data && addResp.data.media_id) || mediaId, file_name: fileName }));
}

main().catch((e) => {
  console.log(JSON.stringify({ success: false, error: String(e.message || e).slice(0, 200) }));
  process.exit(9);
});
