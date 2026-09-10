"""板块四·前端工作台 后端(FastAPI)。

职责四件: ①托管 web/ 静态 SPA ②/wb-api/v1/* 代理数据源 ③本地产物/账本只读视图
④设置与追踪账号读写(仅写 data/workbench/ 自有文件)。
默认绑 127.0.0.1:8788; 对外须显式 --bind(与 sources serve 同一网络红线)。

启动: python cli.py workbench serve [--bind 0.0.0.0] [--port 8788] [--open]
"""

import json
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from fastapi import Body, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, gcompose, omniroute_ctl, ondemand_translate, proxy, retrieve, stats, views, vstudio, x_track, xaccounts, x_profile_enricher, x_reply, x_surge, xsurge_ctl, yt_track

WEB = Path(__file__).resolve().parent.parent / "web"


def _detect_fallback(base: str, key: str, model: str) -> dict:
    """/audio/voices 不存在时: ①/models 找 tts 模型(回填 model 提示)
    ②/chat/completions 发假音色探测, 从错误信息 "Available voices: [...]" 提取清单
    (小米 mimo 类端点实测有效)。"""
    auth = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    hint = ""
    try:
        req = urllib.request.Request(base + "/models", headers=auth)
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.loads(r.read())
        tts_models = [m.get("id") for m in (d.get("data") or [])
                      if "tts" in str(m.get("id", "")).lower()]
        if tts_models:
            hint = f"检测到 TTS 模型: {tts_models[0]}"
            if not model:
                model = tts_models[0]
    except Exception:
        pass
    if model:
        try:
            body = json.dumps({"model": model, "modalities": ["text", "audio"],
                               "audio": {"voice": "__probe__", "format": "mp3"},
                               "messages": [{"role": "assistant", "content": "探测"}]}).encode()
            req = urllib.request.Request(base + "/chat/completions", data=body, headers=auth)
            try:
                urllib.request.urlopen(req, timeout=20)
            except urllib.error.HTTPError as e:
                import re
                m = re.search(r"Available voices[:：]\s*\[([^\]]+)\]",
                              e.read().decode("utf-8", "replace"))
                if m:
                    voices = [{"id": v.strip().strip("'\""), "name": v.strip().strip("'\"")}
                              for v in m.group(1).split(",") if v.strip()]
                    voices = [v for v in voices if v["id"]]
                    if voices:
                        return {"ok": True, "voices": voices, "model": model,
                                "hint": (hint + "; " if hint else "") + "音色来自端点错误枚举"}
        except Exception:
            pass
    return {"ok": False, "hint": hint,
            "error": (hint + ";" if hint else "") + "端点无音色列表接口, 请按文档手动添加音色"}



def create_app() -> FastAPI:
    app = FastAPI(title="aag-workbench", version="0.1", docs_url=None, redoc_url=None)
    vstudio.migrate_legacy_assets()

    # ── 数据源代理(前端唯一取数口) ──────────────────────────────────────────
    @app.get("/wb-api/v1/{path:path}")
    def v1_proxy(path: str, request: Request):
        return proxy.forward(request, path)

    # ── 统计聚合(资讯页右栏 + 来源详情子页, 服务端聚合成品直供) ──────────────
    @app.get("/wb-api/stats")
    def stats_agg():
        try:
            return stats.aggregate()
        except proxy.UpstreamError as e:
            return JSONResponse({"error": str(e)}, status_code=e.code or 502)

    # ── 聚合健康(顶栏健康灯) ────────────────────────────────────────────────
    @app.get("/wb-api/health")
    def health():
        src = {"ok": False}
        t0 = time.time()
        try:
            cfg = config.load()["source"]
            url = cfg["base_url"].rstrip("/") + "/v1/health"
            headers = {"Authorization": f"Bearer {cfg['api_key']}"} if cfg.get("api_key") else {}
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                        timeout=5) as r:
                src = {"ok": True, "ms": int((time.time() - t0) * 1000),
                       **json.loads(r.read())}
        except Exception as e:
            src = {"ok": False, "error": type(e).__name__}
        return {"workbench": "ok", "source": src}

    # ── 设置(唯一写口: data/workbench/settings.json) ─────────────────────────
    @app.get("/wb-api/settings")
    def get_settings():
        return config.public_view(config.load())

    @app.put("/wb-api/settings")
    async def put_settings(request: Request):
        body = await request.json()
        return config.public_view(config.apply_patch(body))

    # ── 只读视图(三板块文件契约) ────────────────────────────────────────────
    @app.get("/wb-api/selfcheck")
    def selfcheck():
        return views.selfcheck()

    @app.get("/wb-api/flows")
    def flows():
        return {"flows": views.flows_list()}

    @app.get("/wb-api/runs")
    def runs():
        return {"runs": views.runs_list()}

    @app.get("/wb-api/artifacts")
    def artifacts():
        return views.artifacts()

    @app.get("/wb-api/artifacts/file")
    def artifact_file(path: str):
        p = views.artifact_file(path)
        if not p:
            return JSONResponse({"error": "文件不存在或越界"}, status_code=404)
        return FileResponse(str(p))

    @app.get("/wb-api/ledger")
    def ledger():
        return views.ledger_rows()

    @app.get("/wb-api/videos")
    def videos():
        return {"videos": views.videos()}

    @app.delete("/wb-api/videos/{vid}")
    def video_delete(vid: str):
        import re
        import subprocess
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", vid):
            return JSONResponse({"error": "bad_vid"}, status_code=400)
        cli = Path(__file__).resolve().parents[2] / "cli.py"
        try:
            result = subprocess.run(
                [*config.py_cmd(), str(cli), "video", "remove", vid],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        except subprocess.TimeoutExpired:
            return JSONResponse({"error": "remove_timeout"}, status_code=504)
        except OSError:
            return JSONResponse({"error": "remove_failed"}, status_code=500)
        if result.returncode != 0:
            return JSONResponse({"error": "remove_failed",
                                 "hint": (result.stderr or result.stdout or "")[-200:]},
                                status_code=400)
        return {"removed": 1}

    @app.post("/wb-api/videos/{vid}/cover")
    async def video_cover(vid: str, request: Request):
        """封面制作：背景+人物形象+标题 → Remotion still 出 out/cover.png。"""
        import re as _re
        if not _re.fullmatch(r"[A-Za-z0-9_\-]+", vid):
            return JSONResponse({"error": "bad_vid"}, status_code=400)
        body = await request.json()
        try:
            return vstudio.run_cover(vid, body)
        except ValueError as e:
            return JSONResponse({"error": "cover_rejected", "hint": str(e)[:200]}, status_code=400)
        except Exception as e:  # 渲染类失败统一 500，hint 带日志尾部
            return JSONResponse({"error": type(e).__name__, "hint": str(e)[:200]}, status_code=500)

    @app.post("/wb-api/videos/{vid}/rename")
    async def video_rename(vid: str, request: Request):
        """重命名视频项目(改 project.json 标题, 经 CLI 子进程写板块二)。"""
        import re
        import subprocess
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", vid):
            return JSONResponse({"error": "bad_vid"}, status_code=400)
        body = await request.json()
        title = str(body.get("title") or "").strip()
        if not title or len(title) > 60:
            return JSONResponse({"error": "标题需为 1-60 字"}, status_code=400)
        cli = Path(__file__).resolve().parents[2] / "cli.py"
        try:
            result = subprocess.run(
                [*config.py_cmd(), str(cli), "video", "rename", vid, "--title", title],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        except subprocess.TimeoutExpired:
            return JSONResponse({"error": "rename_timeout"}, status_code=504)
        except OSError:
            return JSONResponse({"error": "rename_failed"}, status_code=500)
        if result.returncode != 0:
            return JSONResponse({"error": "rename_failed",
                                 "hint": (result.stderr or result.stdout or "")[-200:]},
                                status_code=400)
        return {"renamed": 1, "title": title}

    @app.post("/wb-api/open-folder")
    async def open_folder(request: Request):
        """在资源管理器中打开工作台自有产出目录（语音稿/成片），只允许白名单内的自有目录。"""
        import re
        import subprocess
        body = await request.json()
        kind = body.get("kind")
        make_id = body.get("make_id") or ""
        project_id = body.get("project_id") or ""
        do_open = body.get("open", True)
        if not re.fullmatch(r"[\w\-]*", make_id) or not re.fullmatch(r"[\w\-]*", project_id):
            return JSONResponse({"error": "bad_id"}, status_code=400)
        from . import vmake, vstudio
        target = None
        if kind == "voice" and make_id:
            row = vstudio.make_get(make_id)
            vkey = ((row or {}).get("voice") or {}).get("voice_key") or ""
            if row and vkey:
                target = config.DATA_DIR / "video_voice" / make_id / vkey
            elif make_id:                            # 无激活 take: 回退制作单语音根目录(历史 take)
                make_root = config.DATA_DIR / "video_voice" / make_id
                if make_root.is_dir():
                    target = make_root
        elif kind == "project_out" and project_id:
            if not re.fullmatch(r"[\w\-]+", project_id):
                return JSONResponse({"error": "bad_id"}, status_code=400)
            target = vmake.VIDEOS_DIR / project_id / "out"
        if target is None:
            return JSONResponse({"error": "bad_kind"}, status_code=400)
        target = target.resolve()
        if not target.is_dir():
            return JSONResponse({"error": "folder_not_found", "path": str(target)}, status_code=404)
        if do_open:
            subprocess.Popen(["explorer.exe", str(target)])
        return {"opened": bool(do_open), "path": str(target)}

    @app.get("/wb-api/videos/{vid}/file/{name}")
    def video_file(vid: str, name: str):
        p = views.video_file(vid, name)
        if not p:
            return JSONResponse({"error": "not found"}, status_code=404)
        return FileResponse(str(p))

    # ── X 账号池(只读): 池源条目按账号展示的档案供给 ─────────────────────────
    @app.get("/wb-api/x-accounts")
    def x_accounts():
        return xaccounts.payload()

    @app.get("/wb-api/x-profiles")
    def x_profiles():
        c = x_profile_enricher.load_cache()
        return {"profiles": c["profiles"], "enriched_at": c.get("enriched_at"),
                "count": len(c["profiles"])}

    # ── 账号管理(图文页子页): 全池只读 + 本地偏好(唯一写口 x_account_prefs.json) ──
    @app.get("/wb-api/x-accounts-manage")
    def x_accounts_manage():
        return xaccounts.manage_payload()

    @app.post("/wb-api/x-accounts/{handle}/enabled")
    async def x_account_enabled(handle: str, request: Request):
        body = await request.json()
        on = bool(body.get("on", True))
        try:
            return xaccounts.set_enabled(handle, on)
        except KeyError:
            return JSONResponse({"error": f"池内无此账号: {handle}"}, status_code=404)

    # ── 账号追踪(图文页子页): 自选 X 账号粉丝/增粉/更新/流量日快照 ─────────────
    # 端点零外呼(红线同 yt_track): 读缓存或 spawn CLI; 真抓网只在 refresh-x-track 进程。
    @app.get("/wb-api/xt/overview")
    def xt_overview():
        return x_track.overview_payload()

    @app.get("/wb-api/xt/accounts/{handle}")
    def xt_account(handle: str, days: int = 30):
        d = x_track.account_series(handle, days)
        if not d:
            return JSONResponse({"error": "追踪账号不存在"}, status_code=404)
        return d

    @app.post("/wb-api/xt/accounts")
    async def xt_account_add(request: Request):
        body = await request.json()
        row, err = x_track.add_account(str(body.get("input") or ""),
                                       str(body.get("note") or ""),
                                       bool(body.get("enabled", True)))
        if err:
            dup = "已在追踪列表" in err["error"]
            return JSONResponse(err, status_code=409 if dup else 400)
        return {"added": row}

    @app.delete("/wb-api/xt/accounts/{handle}")
    def xt_account_del(handle: str):
        n = x_track.remove_account(handle)
        if not n:
            return JSONResponse({"error": "追踪账号不存在"}, status_code=404)
        return {"removed": n}    # 日快照随账号一并删除(用户明确增减语义)

    @app.post("/wb-api/xt/accounts/{handle}/enabled")
    async def xt_account_enabled(handle: str, request: Request):
        body = await request.json()
        if not x_track.set_enabled(handle, bool(body.get("on", True))):
            return JSONResponse({"error": "追踪账号不存在"}, status_code=404)
        return {"handle": handle, "enabled": bool(body.get("on", True))}

    @app.post("/wb-api/xt/accounts/{handle}/note")
    async def xt_account_note(handle: str, request: Request):
        body = await request.json()
        if not x_track.set_note(handle, str(body.get("note") or "")):
            return JSONResponse({"error": "追踪账号不存在"}, status_code=404)
        return {"handle": handle, "note": str(body.get("note") or "")[:200]}

    @app.post("/wb-api/xt/import-followed")
    def xt_import_followed():
        return x_track.import_followed()

    @app.post("/wb-api/xt/collect")
    def xt_collect():
        """立即采集: detached spawn CLI(一轮秒级~分钟级, 同步会卡浏览器请求);
        进度经 GET /xt/overview 的 status 轮询(last_collect 落 x_track.json)。"""
        import subprocess
        if x_track.status_payload()["running"]:
            return JSONResponse({"error": "采集进行中", "started_at":
                                 x_track.load_store().get("last_collect", {}).get("started_at")},
                                status_code=409)
        cli = Path(__file__).resolve().parents[2] / "cli.py"
        log_dir = Path(__file__).resolve().parents[2] / "data"
        log_dir.mkdir(parents=True, exist_ok=True)
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP \
            if hasattr(subprocess, "DETACHED_PROCESS") else 0
        try:
            log = open(log_dir / "xtrack_collect.log", "a", encoding="utf-8")
            subprocess.Popen([*config.py_cmd(), str(cli), "workbench",
                              "refresh-x-track", "--json"],
                             cwd=str(Path(__file__).resolve().parents[2]),
                             stdout=log, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL,
                             creationflags=flags, close_fds=True)
        except Exception as e:
            return JSONResponse({"error": f"采集进程启动失败: {e}"}, status_code=500)
        return {"started": True}

    @app.post("/wb-api/xt/schedule")
    async def xt_schedule(request: Request):
        body = await request.json()
        return x_track.schedule(bool(body.get("on", True)))


    # ── 内容生成·信息检索: 素材回查全文/同簇多源/同标的扩展(纯只读, 零 LLM) ────
    @app.post("/wb-api/retrieve")
    async def retrieve_view(request: Request):
        body = await request.json()
        try:
            return retrieve.run(body)
        except proxy.UpstreamError as e:
            return JSONResponse({"error": str(e), "hint": "先跑 python cli.py sources serve"},
                                status_code=e.code or 502)

    # ── 内容生成·成稿编排: 端点零外呼, 只校验 + spawn CLI + 轮询(同 vstudio) ──
    @app.post("/wb-api/gen-compose")
    async def gen_compose(request: Request):
        body = await request.json()
        if gcompose.job_running():
            return JSONResponse({"error": "生成任务进行中, 等它跑完再试"}, status_code=409)
        items = [m for m in (body.get("items") or []) if isinstance(m, dict)][:8]
        if not items:
            return JSONResponse({"error": "no_items", "hint": "先勾选参与生成的素材"},
                                status_code=400)
        gcompose.begin_job({**body, "items": items})
        try:
            gcompose.spawn_cli()
        except Exception as e:
            gcompose.finish_job(3, str(e))
            return JSONResponse({"error": f"生成进程启动失败: {e}"}, status_code=500)
        return {"started": True}

    @app.post("/wb-api/test-llm")
    async def test_llm(request: Request):
        import subprocess
        model_id = ""
        try:                                        # 可选 body: {"model_id": "..."} 只测指定链位
            body = await request.json()
            if isinstance(body, dict):
                model_id = str(body.get("model_id") or "")
        except Exception:
            pass
        cli = Path(__file__).resolve().parents[2] / "cli.py"
        cmd = [*config.py_cmd(), str(cli), "workbench", "test-llm"]
        if model_id:
            cmd += ["--model-id", model_id]
        try:
            p = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=40)
        except subprocess.TimeoutExpired:
            return JSONResponse({"ok": False, "model": "", "error": "cli_timeout"}, status_code=504)
        except OSError:
            return JSONResponse({"ok": False, "model": "", "error": "cli_start_failed"}, status_code=500)
        try:
            out = json.loads(p.stdout)
            if not isinstance(out, dict) or not isinstance(out.get("ok"), bool) or not all(
                    isinstance(out.get(k), str) for k in ("model", "error")):
                raise ValueError("invalid result")
        except (ValueError, TypeError):
            return JSONResponse({"ok": False, "model": "", "error": "invalid_cli_response"}, status_code=502)
        if p.returncode != 0 or not out["ok"]:
            out["ok"] = False
            out["error"] = out["error"] or "llm_connection_failed"
            return JSONResponse(out, status_code=400 if p.returncode == 4 else 502)
        return out

    # ── X 采集一键入口: 纯工作台部署无计划任务, 空态页面上直接拉数(xsurge_ctl) ──
    @app.get("/wb-api/xsurge-status")
    def xsurge_status():
        return xsurge_ctl.status()

    @app.post("/wb-api/xsurge-collect")
    def xsurge_collect():
        try:
            return xsurge_ctl.collect()
        except Exception as e:
            return JSONResponse({"ok": False, "msg": f"collect_failed: {e}"}, status_code=500)

    @app.post("/wb-api/xsurge-schedule")
    def xsurge_schedule():
        try:
            return xsurge_ctl.schedule()
        except Exception as e:
            return JSONResponse({"ok": False, "msg": f"schedule_failed: {e}"}, status_code=500)

    # ── OmniRoute 免费翻译网关: 状态探测 + 一键安装启动(分发用户开箱即用, omniroute_ctl) ──
    @app.get("/wb-api/omniroute-status")
    def omniroute_status():
        return omniroute_ctl.status()

    @app.post("/wb-api/omniroute-setup")
    def omniroute_setup():
        try:
            return omniroute_ctl.setup()
        except Exception as e:
            return JSONResponse({"ok": False, "state": "error", "msg": f"setup_failed: {e}"},
                                status_code=500)

    # ── 浏览层按需翻译: 视口内缺译文卡片批量翻, 哈希缓存落盘, 免费链(ondemand_translate) ──
    @app.post("/wb-api/translate")
    async def wb_translate(request: Request):
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "bad_json"}, status_code=400)
        items = body.get("items")
        if not isinstance(items, list) or not items:
            return JSONResponse({"error": "items 必须是非空数组"}, status_code=400)
        try:
            return ondemand_translate.translate_batch(items)
        except Exception as e:
            return JSONResponse({"error": f"translate_failed: {e}"}, status_code=500)

    @app.get("/wb-api/gen-jobs")
    def gen_jobs():
        return gcompose.status_payload()

    @app.get("/wb-api/gen-posts")
    def gen_posts():
        return {"posts": gcompose.post_list()}

    @app.delete("/wb-api/gen-posts/{pid}")
    def gen_post_delete(pid: str):
        if not gcompose.post_delete(pid):
            return JSONResponse({"error": "post_not_found"}, status_code=404)
        return {"ok": True}

    @app.get("/wb-api/gen-posts/{pid}")
    def gen_post_get(pid: str):
        post = gcompose.post_get(pid)
        if not post:
            return JSONResponse({"error": "post_not_found"}, status_code=404)
        return post

    @app.get("/wb-api/gen-assets/{pid}/{name}")
    def gen_asset(pid: str, name: str):
        f = gcompose.asset_file(pid, name)
        if not f:
            return JSONResponse({"error": "asset_not_found"}, status_code=404)
        return FileResponse(str(f), media_type="image/png")

    @app.post("/wb-api/x-account-pref")
    async def x_account_pref(request: Request):
        body = await request.json()
        handle = str(body.get("handle") or "").strip().lstrip("@").lower()
        if not handle:
            return JSONResponse({"error": "缺少 handle"}, status_code=400)
        if handle not in xaccounts.pool_handles():
            return JSONResponse({"error": f"池内无此账号: {handle}"}, status_code=404)
        prefs = config.load_x_prefs()
        p = prefs.setdefault(handle, {})
        if "follow" in body:
            p["follow"] = bool(body["follow"])
        if "note" in body:
            p["note"] = str(body["note"])[:200]
        p["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        config.save_x_prefs(prefs)
        return {"handle": handle, "follow": p.get("follow", False),
                "note": p.get("note", "")}

    # ── 追踪账号(本板块自有数据, 真实增删; 指标采集留桩) ─────────────────────
    @app.get("/wb-api/track/accounts")
    def track_list():
        return {"accounts": config.load_accounts()}

    @app.post("/wb-api/track/accounts")
    async def track_add(request: Request):
        body = await request.json()
        rows = config.load_accounts()
        rows.append({"platform": body.get("platform", ""), "account": body.get("account", ""),
                     "note": body.get("note", ""),
                     "added_at": time.strftime("%Y-%m-%d %H:%M:%S")})
        return {"accounts": config.save_accounts(rows)}

    @app.delete("/wb-api/track/accounts/{idx}")
    def track_del(idx: int):
        rows = config.load_accounts()
        if 0 <= idx < len(rows):
            rows.pop(idx)
        return {"accounts": config.save_accounts(rows)}

    # ── 关注来源(本板块自有数据: followed_sources.json) ─────────────────────
    @app.get("/wb-api/followed-sources")
    def followed_list():
        rows = config.load_followed()
        return {"rows": rows, "ids": [r["id"] for r in rows]}

    @app.post("/wb-api/followed-sources")
    async def followed_toggle(request: Request):
        body = await request.json()
        sid = str(body.get("id") or "")
        if not sid:
            return JSONResponse({"error": "缺少来源 id"}, status_code=400)
        rows = config.load_followed()
        if body.get("on"):
            if not any(r["id"] == sid for r in rows):
                rows.append({"id": sid, "added_at": time.strftime("%Y-%m-%d %H:%M:%S")})
        else:
            rows = [r for r in rows if r["id"] != sid]
        config.save_followed(rows)
        return {"id": sid, "on": bool(body.get("on")),
                "ids": [r["id"] for r in rows]}

    # ── 来源启停(红线7: 触发类动作只经 subprocess 调 cli.py, 不直写板块一) ────
    @app.post("/wb-api/sources/{sid}/enabled")
    async def source_enabled(sid: str, request: Request):
        body = await request.json()
        on = bool(body.get("on"))
        import subprocess
        cli = Path(__file__).resolve().parents[2] / "cli.py"
        try:
            p = subprocess.run(
                [*config.py_cmd(), str(cli), "sources", "enable", sid, "on" if on else "off", "--json"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        except subprocess.TimeoutExpired:
            return JSONResponse({"error": "cli 调用超时"}, status_code=504)
        try:
            out = json.loads((p.stdout or "").strip().splitlines()[-1])
        except Exception:
            out = {"raw": (p.stdout or p.stderr or "").strip()[:300]}
        if p.returncode != 0 or not out.get("ok"):
            return JSONResponse({"error": out.get("error") or out.get("raw") or f"exit {p.returncode}"},
                                status_code=500)
        stats.invalidate()                  # 60s 统计缓存立即作废, 注册表状态即时生效
        return {"id": sid, "enabled": out.get("enabled")}

    # ── 图文页【推荐信息】数据面: 全 X 条目 + 互动快照五选排序 ────────────────
    @app.get("/wb-api/x-surge")
    def x_surge_view(range: str = "24h", golden: int = 0, market: str = "",
                     sector: str = "", min_followers: int = 0, finance: int = 0,
                     sort: str = "time", limit: int = 100):
        try:
            return x_surge.build_view(range_h=int(range.rstrip("h")) if range.endswith("h") else 24,
                                      golden=bool(golden), market=market, sector=sector,
                                      min_followers=min_followers, finance=bool(finance),
                                      sort=sort, limit=limit)
        except proxy.UpstreamError as e:
            return JSONResponse({"error": str(e)}, status_code=e.code or 502)

    # ── 图文页【蹭蹭流量】数据面: SoPilot 热帖 RSS(唯一来源, 读缓存零外呼) ─────
    @app.get("/wb-api/x-surge-rss")
    def x_surge_rss_view(sort: str = "prob", limit: int = 100):
        return x_surge.rss_view(sort=sort, limit=limit)

    # ── 蹭蹭流量·评论生成: 缓存命中同步直返, 未命中同步 spawn CLI(test-llm 先例;
    #    同步 def 走 Starlette 线程池, LLM 外呼只在 CLI 子进程, 端点零外呼红线不破) ──
    @app.post("/wb-api/x-reply")
    def x_reply_gen(body: dict = Body(default=None)):
        body = body or {}
        sid = str(body.get("status_id") or "")
        force = bool(body.get("force"))
        if not (sid.isdigit() and 5 <= len(sid) <= 25):
            return JSONResponse({"error": "bad_status_id"}, status_code=400)
        try:
            cached = x_reply.cache_get(sid)
        except Exception:
            cached = None
        if cached is not None and not force:
            return {"cached": True, **cached}
        ok, err = x_reply.try_begin(sid, force)
        if not ok:
            return JSONResponse({"error": err}, status_code=429)
        import subprocess
        cli = Path(__file__).resolve().parents[2] / "cli.py"
        try:
            p = subprocess.run(
                [*config.py_cmd(), str(cli), "workbench", "gen-reply",
                 "--status-id", sid] + (["--force"] if force else []),
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
        except subprocess.TimeoutExpired:
            return JSONResponse({"error": "cli_timeout",
                                 "hint": "模型 90 秒未返回, 稍后再试"}, status_code=504)
        except OSError as e:
            return JSONResponse({"error": f"生成进程启动失败: {e}"}, status_code=500)
        finally:
            x_reply.finish(sid)
        try:
            out = json.loads(p.stdout.strip().splitlines()[-1])
            if not isinstance(out, dict):
                raise ValueError("invalid result")
        except (ValueError, TypeError, IndexError):
            return JSONResponse({"error": "invalid_cli_response"}, status_code=502)
        if p.returncode != 0:
            return JSONResponse(out, status_code=400 if p.returncode == 4 else 502)
        return {"cached": False, **out}

    # ── 视频页【热点追踪/追踪账号】: YouTube 账号库+快照增量榜(读缓存零外呼;
    #    外呼只在 /yt/collect spawn 的 CLI 进程, 同 x_surge 架构) ────────────────
    @app.get("/wb-api/yt/hot")
    def yt_hot(range: str = "24h", sort: str = "views", kind: str = "all",
               channel: str = "", q: str = "", limit: int = 100):
        return yt_track.build_view(range=range, sort=sort, kind=kind,
                                   channel=channel, q=q, limit=limit)

    @app.get("/wb-api/yt/status")
    def yt_status():
        return yt_track.status_payload()

    @app.get("/wb-api/yt/channels")
    def yt_channels_list():
        rows = config.load_yt_channels()
        stats = yt_track.channel_stats()      # YTB 追踪标准六项(零外呼读缓存)
        for r in rows:
            r["stats"] = stats.get(r.get("channel_id") or "") or {}
        return {"channels": rows,
                "meta": {"configured": bool(yt_track.api_key()),
                         "enabled": sum(1 for c in rows if c.get("enabled", True)),
                         "pending": sum(1 for c in rows if c.get("resolve_status") == "pending"),
                         "failed": sum(1 for c in rows if c.get("resolve_status") == "failed")}}

    @app.post("/wb-api/yt/channels")
    async def yt_channels_add(request: Request):
        body = await request.json()
        row, err = yt_track.add_channel(str(body.get("input") or ""),
                                        str(body.get("note") or ""),
                                        bool(body.get("enabled", True)))
        if err:
            dup = "已在追踪列表" in err["error"]
            return JSONResponse(err, status_code=409 if dup else 400)
        return {"added": row, "channels": config.load_yt_channels()}

    @app.get("/wb-api/yt/channels/{cid}/series")
    def yt_channel_series(cid: str, days: str = "30"):
        d = yt_track.channel_series(cid, days=int(days) if days.isdigit() else 30)
        if d is None:
            return JSONResponse({"error": "channel_not_found"}, status_code=404)
        return d

    @app.post("/wb-api/yt/channels/{cid}/enabled")
    async def yt_channel_enabled(cid: str, request: Request):
        body = await request.json()
        rows = config.load_yt_channels()
        for r in rows:
            if r.get("id") == cid:
                r["enabled"] = bool(body.get("on"))
                config.save_yt_channels(rows)
                return {"id": cid, "enabled": r["enabled"]}
        return JSONResponse({"error": "频道不存在"}, status_code=404)

    @app.delete("/wb-api/yt/channels/{cid}")
    def yt_channel_del(cid: str):
        rows = [r for r in config.load_yt_channels() if r.get("id") != cid]
        return {"removed": 1, "channels": config.save_yt_channels(rows)}
        # 已采视频/快照保留为孤儿数据(防误删丢历史), 榜单按启用频道过滤自然隐去

    @app.post("/wb-api/yt/channels/import")
    async def yt_channels_import():
        """从追踪主页 tracked_accounts.json 导入 platform=YouTube 的行(只复制不删源)。"""
        imported, skipped = [], []
        rows = config.load_yt_channels()
        seen = {c.get("value") for c in rows}
        for a in config.load_accounts():
            if (a.get("platform") or "").lower() != "youtube":
                continue
            parsed = yt_track.parse_channel_input(a.get("account") or "")
            if not parsed or parsed["value"] in seen:
                skipped.append(a.get("account"))
                continue
            rows.append({"id": "y" + time.strftime("%m%d%H%M%S"),
                         "input": a.get("account"), "kind": parsed["kind"],
                         "value": parsed["value"],
                         "handle": parsed["value"] if parsed["kind"] == "handle" else "",
                         "channel_id": parsed["value"] if parsed["kind"] == "channel_id" else "",
                         "title": "", "note": a.get("note") or "", "enabled": True,
                         "resolve_status": "pending", "resolve_error": "",
                         "subs": None, "uploads_pid": "",
                         "added_at": time.strftime("%Y-%m-%d %H:%M:%S")})
            seen.add(parsed["value"])
            imported.append(a.get("account"))
        if imported:
            config.save_yt_channels(rows)
        return {"imported": imported, "skipped": [s for s in skipped if s],
                "channels": rows}

    @app.post("/wb-api/yt/collect")
    def yt_collect():
        """立即采集: 异步 spawn CLI(一轮 30–120s, 同步会卡死浏览器请求);
        进度/结果经 GET /yt/status 轮询(状态落 yt_videos.json last_collect)。"""
        import subprocess
        st = yt_track.status_payload()
        if not st["configured"]:
            return JSONResponse({"error": "未配置 YouTube Data API Key",
                                 "hint": "到 设置 → YouTube 热点追踪 填写"}, status_code=400)
        if st["running"]:
            return JSONResponse({"error": "采集进行中", "started_at": st["started_at"]},
                                status_code=409)
        cli = Path(__file__).resolve().parents[2] / "cli.py"
        try:
            subprocess.Popen(
                [*config.py_cmd(), str(cli), "workbench", "refresh-yt-track", "--json"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as e:
            return JSONResponse({"error": f"采集进程启动失败: {e}"}, status_code=500)
        return {"started": True}

    # ── 视频工坊: 端点只读/写自有 JSON；分析与生成仅 spawn CLI 外呼 ──────────
    def start_video_job(kind, payload, command):
        import subprocess
        if vstudio.job_running(kind):
            return JSONResponse({"error": "任务进行中"}, status_code=409)
        vstudio.begin_job(kind, payload)
        cli = Path(__file__).resolve().parents[2] / "cli.py"
        try:
            subprocess.Popen([*config.py_cmd(), str(cli), "workbench", command, "--json"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError:
            vstudio.finish_job(kind, 3, "cli_start_failed")
            return JSONResponse({"error": "cli_start_failed"}, status_code=500)
        return {"started": True}

    @app.get("/wb-api/video-makes")
    def video_makes():
        return {"makes": vstudio.makes_view()}

    @app.post("/wb-api/video-makes")
    async def video_make_upsert(request: Request):
        row = vstudio.make_upsert(await request.json())
        return {"make": row} if row else JSONResponse({"error": "make_not_found"}, status_code=404)

    @app.get("/wb-api/video-makes/{mid}")
    def video_make_get(mid: str):
        row = vstudio.make_get(mid)
        return {"make": vstudio.make_view(row)} if row else JSONResponse({"error": "make_not_found"}, status_code=404)

    @app.delete("/wb-api/video-makes/{mid}")
    def video_make_delete(mid: str):
        return {"removed": vstudio.make_del(mid)}

    @app.post("/wb-api/video-makes/{mid}/duplicate")
    def video_make_duplicate(mid: str):
        row = vstudio.make_duplicate(mid)
        return {"make": row} if row else JSONResponse({"error": "make_not_found"}, status_code=404)

    def make_lock_response(result):
        row, err = result
        return JSONResponse(err, status_code=400) if err else {"make": row}

    @app.post("/wb-api/video-makes/{mid}/lock-narration")
    def video_lock_narration(mid: str):
        return make_lock_response(vstudio.lock_narration(mid))

    @app.post("/wb-api/video-makes/{mid}/unlock-narration")
    def video_unlock_narration(mid: str):
        return make_lock_response(vstudio.unlock_narration(mid))

    @app.post("/wb-api/video-makes/{mid}/lock-script")
    def video_lock_script(mid: str):
        return make_lock_response(vstudio.lock_script(mid))

    @app.post("/wb-api/video-makes/{mid}/unlock-script")
    def video_unlock_script(mid: str):
        return make_lock_response(vstudio.unlock_script(mid))

    @app.post("/wb-api/video-narration/generate")
    async def video_narration_generate(request: Request):
        body = await request.json()
        if vstudio.job_running("generate"):
            return JSONResponse({"error": "任务进行中"}, status_code=409)
        if body.get("style_id") not in vstudio._STYLES:
            return JSONResponse({"error": "bad_style"}, status_code=400)
        return start_video_job("generate", {**body, "task": "narration"}, "gen-narration")

    @app.post("/wb-api/video-storyboard/generate")
    async def video_storyboard_generate(request: Request):
        body = await request.json()
        if vstudio.job_running("generate"):
            return JSONResponse({"error": "任务进行中"}, status_code=409)
        row = vstudio.make_get(body.get("make_id"))
        if not row or not row["narration"]["locked"]:
            return JSONResponse({"error": "narration_not_locked" if row else "make_not_found"}, status_code=400)
        return start_video_job("generate", {"task": "storyboard", "make_id": row["id"]}, "gen-script")

    @app.post("/wb-api/video-voice/generate")
    async def video_voice_generate(request: Request):
        body = await request.json()
        if vstudio.job_running("voice"):
            return JSONResponse({"error": "任务进行中"}, status_code=409)
        row = vstudio.make_get(body.get("make_id"))
        if not row or not row["script_meta"]["locked"]:
            return JSONResponse({"error": "script_not_locked"}, status_code=400)
        if not vstudio._tts_provider(body.get("provider_id"), body.get("voice")):
            return JSONResponse({"error": "bad_provider"}, status_code=400)
        return start_video_job("voice", body, "gen-voice")

    @app.get("/wb-api/video-voice/{make_id}/{voice_key}/{beat}.mp3")
    def video_voice_file(make_id: str, voice_key: str, beat: str):
        if not all(vstudio._safe_id(x) for x in (make_id, voice_key, beat)):
            return JSONResponse({"error": "not_found"}, status_code=404)
        path = vstudio._voice_file(make_id, voice_key, f"{beat}.mp3")
        return FileResponse(str(path), media_type="audio/mpeg") if path else JSONResponse({"error": "not_found"}, status_code=404)

    @app.put("/wb-api/video-assets")
    async def video_asset_add(request: Request):
        name = request.query_params.get("name", "")
        ext = Path(name).suffix.lower().lstrip(".")
        if ext not in vstudio.ASSET_KIND:
            return JSONResponse({"error": "bad_ext"}, status_code=400)
        limit = vstudio.ASSET_LIMITS[vstudio.ASSET_KIND[ext]]
        try:
            duration_s = float(request.query_params.get("duration_s", ""))
            if not (-float("inf") < duration_s < float("inf")):
                duration_s = None
        except ValueError:
            duration_s = None
        try:
            length = int(request.headers.get("content-length", "0"))
        except ValueError:
            return JSONResponse({"error": "bad_content_length"}, status_code=400)
        if length > limit:
            return JSONResponse({"error": "too_large"}, status_code=400)
        body = await request.body()
        if not body:
            return JSONResponse({"error": "empty_body"}, status_code=400)
        if len(body) > limit:
            return JSONResponse({"error": "too_large"}, status_code=400)
        asset, err = vstudio.asset_add(name, body, duration_s)
        return JSONResponse(err, status_code=400) if err else {"asset": asset}

    @app.get("/wb-api/video-assets")
    def video_assets():
        return {"assets": vstudio.assets_list()}

    @app.get("/wb-api/video-assets/{asset_id}/file")
    def video_asset_file(asset_id: str):
        path, _ = vstudio.asset_find(asset_id)
        if not path:
            return JSONResponse({"error": "not_found"}, status_code=404)
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp",
                "mp4": "video/mp4", "webm": "video/webm", "mp3": "audio/mpeg",
                "wav": "audio/wav", "m4a": "audio/mp4"}[path.suffix.lower().lstrip(".")]
        return FileResponse(str(path), media_type=mime)

    @app.delete("/wb-api/video-assets/{asset_id}")
    def video_asset_delete(asset_id: str, force: str = ""):
        result = vstudio.asset_del(asset_id, force=force.lower() in ("1", "true"))
        if not result["ok"]:
            refs = result["refs"]
            count = len({r["make_id"] for r in refs})
            names = "、".join(f"{r['title']}×{r['beat_id']}" for r in refs)
            return JSONResponse({"error": "asset_in_use", "refs": refs,
                                 "hint": f"被 {count} 个制作引用: {names}"}, status_code=409)
        return {"removed": 1, "cleared_overrides": result["cleared_overrides"]}

    @app.post("/wb-api/video-assets/{asset_id}/rename")
    async def video_asset_rename(asset_id: str, request: Request):
        try:
            body = await request.json()
        except ValueError:
            body = None
        name = body.get("name") if isinstance(body, dict) else None
        if not isinstance(name, str) or not name.strip():
            return JSONResponse({"error": "bad_name"}, status_code=400)
        asset = vstudio.asset_rename(asset_id, name)
        return {"asset": asset} if asset else JSONResponse({"error": "asset_not_found"}, status_code=404)

    @app.get("/wb-api/video-templates")
    def video_templates():
        return vstudio.templates_catalog()

    @app.post("/wb-api/video-style")
    async def video_style(request: Request):
        from . import vmake
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return JSONResponse({"error": "bad_body"}, status_code=400)
        vs = config.load().get("video_studio") or {}
        vs = dict(vs) if isinstance(vs, dict) else {}
        allowed = {"default_theme": vmake.THEMES, "default_layout": vmake.LAYOUTS,
                   "default_generation_method": {m["id"] for m in vmake.GENERATION_METHODS} | {"inherit"}}
        for key, values in allowed.items():
            if key in body:
                if not isinstance(body[key], str) or body[key] not in values:
                    return JSONResponse({"error": "bad_" + key}, status_code=400)
                vs[key] = body[key]
        favorites = vs.get("favorites") or []
        favorites = list(dict.fromkeys(x for x in favorites if isinstance(x, str))) if isinstance(favorites, list) else []
        if "favorite" in body:
            favorite = body["favorite"]
            keys = {c["key"] for c in vstudio.templates_catalog()["cards"]}
            if (not isinstance(favorite, dict) or not isinstance(favorite.get("key"), str)
                    or favorite["key"] not in keys or not isinstance(favorite.get("on"), bool)):
                return JSONResponse({"error": "bad_favorite"}, status_code=400)
            key = favorite["key"]
            if favorite["on"] and key not in favorites:
                favorites.append(key)
            elif not favorite["on"]:
                favorites = [x for x in favorites if x != key]
        vs["favorites"] = favorites
        saved = config.apply_patch({"video_studio": vs})
        return {"video_studio": saved["video_studio"]}



    @app.post("/wb-api/tts-voices-detect")
    async def tts_voices_detect(request: Request):
        """自定义供应商: 在线检测支持的预设音色。尝试 GET {base}/audio/voices,
        兼容多种返回形状; 不支持的端点明确报错, 让用户回手动添加。"""
        body = await request.json()
        # 已保存供应商: 表单留空的字段回退存储值(key 打码后用户点检测仍可用真实 key)
        saved = next((p for p in (config.load().get("tts") or {}).get("providers", [])
                      if p.get("id") == str(body.get("provider_id") or "")), None)             if body.get("provider_id") else None
        base = str(body.get("base_url") or "") or (saved or {}).get("base_url", "")
        key = str(body.get("api_key") or "") or (saved or {}).get("api_key", "")
        model = str(body.get("model") or "") or (saved or {}).get("model", "")
        if not base:
            return {"ok": False, "error": "先填接口地址"}
        url = base + "/audio/voices"
        try:
            if "minimax" in base:                  # MiniMax: get_voice 只列自建音色,
                                                   # 系统预设不返回 → 空则回官方预设库
                voices = []
                for vtype in ("all", "system"):
                    try:
                        vb = json.dumps({"voice_type": vtype}).encode()
                        req = urllib.request.Request(base + "/get_voice", data=vb,
                            headers={"Authorization": f"Bearer {key}",
                                     "Content-Type": "application/json"})
                        with urllib.request.urlopen(req, timeout=15) as r:
                            d = json.loads(r.read())
                        for v in (d.get("system_voice_list") or d.get("voices")
                                  or d.get("data") or []):
                            vid = str(v.get("voice_id") or v.get("id") or "")
                            if vid and not any(x["id"] == vid for x in voices):
                                voices.append({"id": vid,
                                               "name": str(v.get("voice_name") or v.get("name") or vid)})
                    except Exception:
                        continue
                if voices:
                    return {"ok": True, "voices": voices,
                            "hint": "含账号自建音色"}
                # 官方预设语音库(MiniMax T2A 文档标准集, 无需接口)
                presets = [
                    ("male-qn-qingse", "青涩青年·男"), ("male-qn-jingying", "精英青年·男"),
                    ("male-qn-badao", "霸道青年·男"), ("male-qn-daxuesheng", "大学生·男"),
                    ("female-shaonv", "少女·女"), ("female-yujie", "御姐·女"),
                    ("female-chengshu", "成熟·女"), ("female-tianmei", "甜美·女"),
                    ("male-guangchangbo", "男播音"), ("female-yuanqi", "元气·女"),
                    ("presenter_male", "主持人·男"), ("presenter_female", "主持人·女"),
                    ("audiobook_male_1", "有声书·男1"), ("audiobook_female_1", "有声书·女1"),
                    ("audiobook_male_2", "有声书·男2"), ("audiobook_female_2", "有声书·女2"),
                ]
                return {"ok": True, "model": model or "speech-2.8-hd",
                        "voices": [{"id": v, "name": n} for v, n in presets],
                        "hint": "get_voice 为空(无自建音色), 已给官方预设语音库"}
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
            with urllib.request.urlopen(req, timeout=15) as r:
                d = json.loads(r.read())
            raw = d if isinstance(d, list) else (d.get("voices") or d.get("data") or [])
            voices = []
            for v in raw:
                if isinstance(v, str):
                    voices.append({"id": v, "name": v})
                elif isinstance(v, dict):
                    vid = str(v.get("id") or v.get("voice") or v.get("name") or "")
                    if vid:
                        voices.append({"id": vid, "name": str(v.get("name") or vid)})
            if not voices:
                return {"ok": False, "error": "端点响应为空, 请手动添加音色"}
            return {"ok": True, "voices": voices}
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return _detect_fallback(base, key, model)
            return {"ok": False, "error": f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:120]}"}
        except Exception as e:
            return {"ok": False, "error": f"检测失败: {type(e).__name__}: {str(e)[:100]}"}

    @app.post("/wb-api/test-tts")
    async def test_tts(request: Request):
        import subprocess
        body = await request.json()
        cli = Path(__file__).resolve().parents[2] / "cli.py"
        try:
            tts_args = [*config.py_cmd(), str(cli), "workbench", "test-tts",
                        "--provider", str(body.get("provider_id") or ""),
                        "--voice", str(body.get("voice") or "")]
            if body.get("text"):
                tts_args += ["--text", str(body["text"])]
            proc = subprocess.run(tts_args,
                                  
                                  capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        except subprocess.TimeoutExpired:
            return JSONResponse({"ok": False, "error": "cli_timeout"}, status_code=504)
        except OSError:
            return JSONResponse({"ok": False, "error": "cli_start_failed"}, status_code=500)
        try:
            out = json.loads(proc.stdout.strip().splitlines()[-1])
            if not isinstance(out, dict):
                raise ValueError("invalid result")
        except (ValueError, IndexError, AttributeError):
            return JSONResponse({"ok": False, "error": "invalid_cli_response"}, status_code=502)
        if proc.returncode == 0 and out.get("ok") is True and isinstance(out.get("url"), str):
            return {"ok": True, "url": out["url"]}
        return JSONResponse({"ok": False, "error": out.get("error") or "tts_failed"},
                            status_code=400 if proc.returncode == 4 else 502)

    @app.get("/wb-api/video-pool")
    def video_pool_list():
        return vstudio.pool_view()

    @app.post("/wb-api/video-pool")
    async def video_pool_add(request: Request):
        body = await request.json()
        row, err = vstudio.pool_add(body)
        if err and err.get("error") == "dup":
            return {"added": False}
        if err:
            return JSONResponse(err, status_code=400)
        return {"added": True, "item": row, "meta": vstudio.pool_view()["meta"]}

    @app.delete("/wb-api/video-pool/{pid}")
    def video_pool_del(pid: str):
        removed = vstudio.pool_del(pid)
        return {"removed": removed, "meta": vstudio.pool_view()["meta"]}

    @app.get("/wb-api/video-analyses")
    def video_analyses(key: str = ""):
        if not key:
            return vstudio.analyses_index()
        record = vstudio.analysis_get(key)
        if not record:
            return JSONResponse({"error": "analysis_not_found"}, status_code=404)
        return record

    @app.post("/wb-api/video-analyses/{key}/rename")
    async def video_analysis_rename(key: str, request: Request):
        import re as _re
        if not _re.fullmatch(r"[\w\-]+", key):
            return JSONResponse({"error": "bad_key"}, status_code=400)
        body = await request.json()
        try:
            return vstudio.analysis_rename(key, str(body.get("title") or ""))
        except ValueError as e:
            return JSONResponse({"error": "rename_rejected", "hint": str(e)}, status_code=400)

    @app.delete("/wb-api/video-analyses/{key}")
    def video_analysis_delete(key: str):
        import re as _re
        if not _re.fullmatch(r"[\w\-]+", key):
            return JSONResponse({"error": "bad_key"}, status_code=400)
        try:
            return vstudio.analysis_delete(key)
        except ValueError as e:
            return JSONResponse({"error": "delete_rejected", "hint": str(e)}, status_code=400)

    @app.post("/wb-api/video-analyze")
    async def video_analyze(request: Request):
        import subprocess
        body = await request.json()
        if vstudio.job_running("analyze"):
            return JSONResponse({"error": "分析任务进行中"}, status_code=409)
        cfg = config.load()
        gemini_ok = bool((cfg.get("gemini") or {}).get("api_key"))
        translate = cfg.get("translate") or {}
        translate_ok = all(translate.get(k) for k in ("base_url", "api_key", "model"))
        if not gemini_ok and not translate_ok:
            return JSONResponse({"error": "no_llm_config",
                                 "hint": "到设置页配置 Gemini 或翻译模型"}, status_code=400)
        if body.get("pool_id"):
            row = next((r for r in config.load_video_pool()
                        if r.get("id") == body.get("pool_id")), None)
            if not row:
                return JSONResponse({"error": "pool_not_found"}, status_code=400)
            result_key = vstudio.analysis_key_of(row.get("video_id") or "", row.get("url") or "")
        elif body.get("local_path"):
            import os as _os
            ap = _os.path.abspath(str(body.get("local_path")))
            roots = [p for p in ((cfg.get("analysis_paths") or {}).get("paths") or []) if p]
            if not (_os.path.isfile(ap)
                    and any(ap.startswith(_os.path.abspath(p)) for p in roots)):
                return JSONResponse({"error": "bad_local_path",
                                     "hint": "仅允许分析已配置路径下的视频文件(设置→视频分析路径)"},
                                    status_code=400)
            fp = Path(ap).resolve()
            result_key = vstudio.analysis_key_of("", f"local:{fp}")   # 与 CLI 侧 _target 同构, key 一致
        else:
            parsed = vstudio.parse_video_input(str(body.get("url") or ""))
            if not parsed:
                return JSONResponse({"error": "bad_video_input"}, status_code=400)
            result_key = vstudio.analysis_key_of(parsed["video_id"], parsed["url"])
        vstudio.begin_job("analyze", body)
        cli = Path(__file__).resolve().parents[2] / "cli.py"
        try:
            subprocess.Popen(
                [*config.py_cmd(), str(cli), "workbench", "analyze-video", "--json"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as e:
            vstudio.finish_job("analyze", 3, str(e))
            return JSONResponse({"error": f"分析进程启动失败: {e}"}, status_code=500)
        return {"started": True, "key": result_key}

    @app.get("/wb-api/video-jobs")
    def video_jobs():
        return vstudio.status_payload()

    # ── 视频分析·本地文件(4个可配置扫描根, 设置页可改) ────────────────────────
    @app.get("/wb-api/analysis-paths")
    def analysis_paths():
        slots = (config.load().get("analysis_paths") or {}).get("paths") or []
        return {"paths": [{"idx": i, "label": f"路径{i + 1}", "root": p,
                           "configured": bool(p)} for i, p in enumerate(slots[:4])]}

    @app.get("/wb-api/analysis-files")
    def analysis_files(idx: int = 0):
        import os as _os
        slots = (config.load().get("analysis_paths") or {}).get("paths") or []
        root = slots[idx] if 0 <= idx < len(slots) else ""
        files, err = [], ""
        if not root:
            err = "该路径未配置(设置 → 视频分析路径)"
        elif not _os.path.isdir(root):
            err = f"路径不存在: {root}"
        else:
            exts = {e.lower() for e in vstudio._VIDEO_MIME}
            for base, _dirs, names in _os.walk(root):
                for nm in names:
                    if _os.path.splitext(nm)[1].lower() in exts:
                        fp = _os.path.join(base, nm)
                        try:
                            st = _os.stat(fp)
                        except OSError:
                            continue
                        files.append({"name": nm, "path": fp, "size": st.st_size,
                                      "mtime": int(st.st_mtime)})
            files.sort(key=lambda x: -x["mtime"])
            files = files[:200]
            if not files:
                err = "该路径下暂无视频文件(mp4/mov/mkv/webm/avi…)"
        return {"root": root, "files": files, "error": err or None}

    @app.get("/wb-api/video-script/styles")
    def video_script_styles():
        return {"styles": [{k: style[k] for k in ("id", "name", "format", "target_s", "wc", "prompt")}
                           for style in vstudio.STYLE_PRESETS]}

    @app.post("/wb-api/video-script/generate")
    async def video_script_generate(request: Request):
        import subprocess
        body = await request.json()
        if vstudio.job_running("generate"):
            return JSONResponse({"error": "脚本生成任务进行中"}, status_code=409)
        style_ids = {style["id"] for style in vstudio.STYLE_PRESETS}
        style_id = str(body.get("style_id") or "")
        if style_id not in style_ids:
            return JSONResponse({"error": "bad_style"}, status_code=400)
        if style_id == "from-analysis" and not body.get("analysis_key"):
            return JSONResponse({"error": "analysis_required"}, status_code=400)
        if not any(str(body.get(k) or "").strip() for k in ("brief", "draft_id", "pasted")):
            return JSONResponse({"error": "no_input",
                                 "hint": "填一句话简报、粘贴文章或选草稿"}, status_code=400)
        vstudio.begin_job("generate", body)
        cli = Path(__file__).resolve().parents[2] / "cli.py"
        try:
            subprocess.Popen(
                [*config.py_cmd(), str(cli), "workbench", "gen-script", "--json"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as e:
            vstudio.finish_job("generate", 3, str(e))
            return JSONResponse({"error": f"生成进程启动失败: {e}"}, status_code=500)
        return {"started": True}

    @app.get("/wb-api/video-scripts")
    def video_scripts_list():
        return {"scripts": vstudio.scripts_view()}

    @app.post("/wb-api/video-scripts")
    async def video_scripts_add(request: Request):
        body = await request.json()
        kind = str(body.get("kind") or "")
        if kind == "generated" and not isinstance(body.get("script"), dict):
            return JSONResponse({"error": "generated_requires_script"}, status_code=400)
        if kind == "analysis_seed" and not isinstance(body.get("script"), dict):
            key = str(body.get("analysis_key") or "")
            record = vstudio.analysis_get(key) if key else None
            if not record:
                return JSONResponse({"error": "analysis_required"}, status_code=400)
            body["script"] = vstudio.seed_from_analysis(record)
            body.setdefault("title", body["script"].get("title"))
            body.setdefault("style_id", "from-analysis")
        if kind not in ("generated", "analysis_seed"):
            return JSONResponse({"error": "bad_kind"}, status_code=400)
        return {"script": vstudio.script_add(body)}

    @app.get("/wb-api/video-scripts/{sid}")
    def video_scripts_get(sid: str):
        row = vstudio.script_get(sid)
        if not row:
            return JSONResponse({"error": "script_not_found"}, status_code=404)
        return row

    @app.post("/wb-api/video-scripts/{sid}")
    async def video_scripts_update(sid: str, request: Request):
        row = vstudio.script_update(sid, await request.json())
        if not row:
            return JSONResponse({"error": "script_not_found"}, status_code=404)
        return {"script": row}

    @app.delete("/wb-api/video-scripts/{sid}")
    def video_scripts_del(sid: str):
        return {"removed": vstudio.script_del(sid)}

    # ── 视频工坊·制作(build): 零外呼, 唯一动作是 spawn CLI 子进程真渲染(分钟级) ──
    @app.get("/wb-api/video-presets")
    def video_presets():
        return vstudio.build_presets()

    @app.post("/wb-api/video-build")
    async def video_build(request: Request):
        import subprocess
        from .vmake import (ASPECTS, FORMAT_ALIASES, THEMES, LAYOUTS, LEGACY_PACK_MAP,
                            normalize_aspect, normalize_fps, normalize_style_pack)
        body = await request.json()
        # 脚本来源: script_id 查脚本仓库, 或 body.script 直接带 beats
        if body.get("make_id"):
            row = vstudio.make_get(body["make_id"])
            if not row:
                return JSONResponse({"error": "make_not_found"}, status_code=400)
            if not row["script"] or not row["script_meta"]["locked"]:
                return JSONResponse({"error": "script_not_locked"}, status_code=400)
            mode = body.get("mode") or "build"
            if mode not in ("build", "estimate", "keyframes", "sample"):
                mode = "build"
            missing = vstudio.voice_missing(row)
            if mode != "estimate" and missing:
                return JSONResponse({"error": "voice_missing", "hint": "缺少语音：" + "、".join(missing)}, status_code=400)
            project_id = vstudio._id("wb")
            result = start_video_job("build", {"make_id": row["id"], "project_id": project_id,
                "mode": mode, "hook_index": row["video"].get("hook_index")}, "build-video")
            return {**result, "project_id": project_id} if isinstance(result, dict) else result
        script = None
        if body.get("script_id"):
            row = vstudio.script_get(str(body.get("script_id")))
            if not row or not isinstance(row.get("script"), dict):
                return JSONResponse({"error": "script_not_found",
                                     "hint": "脚本仓库中没有该脚本"}, status_code=400)
            script = row["script"]
        elif isinstance(body.get("script"), dict):
            script = body["script"]
        if not script or not isinstance(script.get("beats"), list) or not script.get("beats"):
            return JSONResponse({"error": "no_script",
                                 "hint": "需要 script_id 或带 beats 的 script"}, status_code=400)
        if vstudio.job_running("build"):
            return JSONResponse({"error": "制作任务进行中"}, status_code=409)
        aspect = body.get("aspect")
        if not isinstance(aspect, str) or aspect not in ASPECTS:
            old_format = body.get("format")
            aspect = normalize_aspect(FORMAT_ALIASES.get(old_format, old_format)
                                      if isinstance(old_format, str) else None)
        fps = normalize_fps(body.get("fps"))
        sp = normalize_style_pack(body.get("style_pack"))
        theme, layout = body.get("theme"), body.get("layout")
        theme = theme if isinstance(theme, str) and theme in THEMES else LEGACY_PACK_MAP[sp][0]
        layout = layout if isinstance(layout, str) and layout in LAYOUTS else LEGACY_PACK_MAP[sp][1]
        tts_provider = str(body.get("tts_provider") or "edge")
        if tts_provider not in ("edge", "dashscope", "custom", "volc"):
            tts_provider = "edge"
        if theme == "vox-collage" and aspect != "16:9":
            return JSONResponse({"error": "aspect_unsupported",
                                 "hint": "VOX 纸拼贴主题仅支持 16:9 画幅，请改选模板动效或切回 16:9"},
                                status_code=400)
        if layout == "fast-cut" and aspect != "16:9":
            return JSONResponse({"error": "aspect_unsupported",
                                 "hint": "快切编排仅支持 16:9 画幅，请改选其他编排或切回 16:9"},
                                status_code=400)
        if tts_provider == "dashscope" and not vstudio.build_presets()["dashscope_key_ok"]:
            return JSONResponse({"error": "dashscope_key_missing",
                                 "hint": "DASHSCOPE_API_KEY 未配置（ai-workflow/video/.env）"},
                                status_code=400)
        enrich = str(body.get("enrich") or "plain")
        if enrich not in ("plain", "llm"):
            enrich = "plain"
        mode = str(body.get("mode") or "build")
        if mode not in ("build", "estimate"):
            mode = "build"
        try:
            hook_index = int(body.get("hook_index"))
        except (TypeError, ValueError):
            hook_index = None
        if hook_index is not None and not 0 <= hook_index <= 2:
            hook_index = None
        title = str(body.get("title") or "").strip()[:30] \
            or str(script.get("title") or "").strip()[:30]
        settings = {"aspect": aspect, "fps": fps, "theme": theme, "layout": layout,
                    "voice": str(body.get("voice") or ""),
                    "tts_provider": tts_provider, "enrich": enrich, "title": title}
        project_id = "wb" + time.strftime("%m%d%H%M%S")
        vstudio.begin_job("build", {"script": script, "settings": settings,
                                    "project_id": project_id, "mode": mode,
                                    "hook_index": hook_index,
                                    "text": str(body.get("text") or "")})
        cli = Path(__file__).resolve().parents[2] / "cli.py"
        try:
            subprocess.Popen(
                [*config.py_cmd(), str(cli), "workbench", "build-video", "--json"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as e:
            vstudio.finish_job("build", 3, str(e))
            return JSONResponse({"error": f"制作进程启动失败: {e}"}, status_code=500)
        return {"started": True, "project_id": project_id}

    @app.get("/wb-api/video-builds/{pid}/log")
    def video_build_log(pid: str, n: int = 100):
        import re
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", pid):
            return JSONResponse({"error": "bad_pid"}, status_code=400)
        log_file = vstudio.BUILD_LOG_DIR / f"{pid}.log"
        if not log_file.is_file():
            return JSONResponse({"error": "log_not_found"}, status_code=404)
        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        n = max(1, min(int(n or 100), 1000))
        return {"tail": lines[-n:], "truncated": len(lines) > n}


    # ── 图文页: 草稿真实 CRUD(data/workbench/drafts.json) ────────────────────
    @app.get("/wb-api/drafts")
    def drafts_list():
        rows = config.load_drafts()
        rows.sort(key=lambda r: r.get("updated_at", ""), reverse=True)
        return {"drafts": rows}

    @app.post("/wb-api/drafts")
    async def drafts_save(request: Request):
        body = await request.json()
        rows = config.load_drafts()
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        did = body.get("id")
        if did:                                       # 有 id = 更新
            for r in rows:
                if r.get("id") == did:
                    r.update({k: body[k] for k in
                              ("title", "content", "items", "modules", "template", "publish", "gen")
                              if k in body})
                    r["updated_at"] = now
                    break
            else:
                return JSONResponse({"error": f"草稿不存在: {did}"}, status_code=404)
        else:                                         # 无 id = 新建
            did = "d" + time.strftime("%m%d%H%M%S")
            rows.append({"id": did, "title": body.get("title") or "未命名草稿",
                         "content": body.get("content", ""),
                         "items": body.get("items") or [],
                         "modules": body.get("modules") or [],
                         "template": body.get("template", ""),
                         "publish": body.get("publish") or {},
                         "gen": body.get("gen") or {},
                         "created_at": now, "updated_at": now})
        return {"drafts": config.save_drafts(rows), "id": did}

    @app.delete("/wb-api/drafts/{did}")
    def drafts_del(did: str):
        rows = [r for r in config.load_drafts() if r.get("id") != did]
        return {"drafts": config.save_drafts(rows)}

    # ── 图文页: 自动化任务真实 CRUD(data/workbench/automation.json, 调度留桩) ──
    @app.get("/wb-api/automation")
    def automation_list():
        return {"tasks": config.load_automation()}

    @app.post("/wb-api/automation")
    async def automation_add(request: Request):
        body = await request.json()
        rows = config.load_automation()
        rows.append({"id": "a" + time.strftime("%m%d%H%M%S"),
                     "name": body.get("name") or "未命名任务",
                     "note": body.get("note", ""),
                     "template": body.get("template", ""),
                     "modules": body.get("modules") or [],
                     "schedule": body.get("schedule") or {"kind": "daily", "time": "08:00"},
                     "publish": body.get("publish") or {"target": "draft"},
                     "enabled": bool(body.get("enabled", True)),
                     "created_at": time.strftime("%Y-%m-%d %H:%M:%S")})
        return {"tasks": config.save_automation(rows)}

    @app.delete("/wb-api/automation/{tid}")
    def automation_del(tid: str):
        rows = [r for r in config.load_automation() if r.get("id") != tid]
        return {"tasks": config.save_automation(rows)}

    # ── 云端同步预留桩(本期一律 501) ─────────────────────────────────────────
    @app.post("/wb-api/cloud/{action}")
    def cloud_stub(action: str):
        return JSONResponse({"error": "云端同步将在后续版本开放",
                             "hint": "本期为纯本地版; 该接口形状已定型(见 docs/第四板块-前端工作台方案.md)"},
                            status_code=501)

    # ── 静态 SPA(放最后, 兜底所有非 /wb-api 路径到 index.html) ───────────────
    # SPA 静态资源禁启发式缓存: 迭代期旧 JS/CSS 被 webview 缓存会导致新旧混载
    @app.middleware("http")
    async def no_cache_static(request: Request, call_next):
        resp = await call_next(request)
        if not request.url.path.startswith("/wb-api"):
            resp.headers["Cache-Control"] = "no-cache"
        return resp

    app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")
    return app


def run(host: str = "127.0.0.1", port: int = 8788, open_browser: bool = False) -> int:
    import uvicorn
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(f"⚠ 对外绑定 {host}——确认走内网/隧道, 禁裸开公网(与 sources serve 同一红线)")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}/")).start()
    print(f"工作台已启动: http://127.0.0.1:{port}/  (数据站: 请先 python cli.py sources serve)")
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")
    return 0
