"""Streamlit 进度轮询组件。

由于 Streamlit 是服务端渲染框架，无法直接在 Python 中持有 WebSocket 连接。
使用短间隔 HTTP 轮询（1 秒间隔）实现同等的实时进度体验。
"""

import time
import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT))

API_BASE = "http://localhost:8000"


def _api_available() -> bool:
    try:
        import requests
        resp = requests.get(f"{API_BASE}/api/v1/health/ready", timeout=2)
        return resp.status_code == 200
    except Exception:
        return False


def _get_json(path: str) -> dict | None:
    import requests
    try:
        resp = requests.get(f"{API_BASE}{path}", timeout=5)
        if resp.status_code >= 400:
            return None
        return resp.json()
    except Exception:
        return None


def poll_task_progress(task_id: str, poll_interval: float = 1.0,
                      max_duration: float = 600.0) -> dict:
    """轮询单票研究任务进度并渲染进度条。

    在提交异步任务后调用。循环轮询 GET /api/v1/research/{task_id}，
    实时更新 Streamlit 进度条和状态文字。
    最多轮询 max_duration 秒（默认 10 分钟），超时后返回失败状态。

    Returns:
        最终的任务状态 dict（status 为 completed/failed/cancelled）
    """
    import requests

    started = time.time()
    status_text = st.empty()
    progress_bar = st.progress(0.0, text="排队中...")

    while time.time() - started < max_duration:
        try:
            resp = requests.get(
                f"{API_BASE}/api/v1/research/{task_id}", timeout=5
            )
            if resp.status_code >= 400:
                status_text.error(f"查询失败 [{resp.status_code}]")
                time.sleep(poll_interval)
                continue
            data = resp.json()
        except requests.ConnectionError:
            status_text.error("无法连接 API 服务，请确认 FastAPI 已启动。")
            return {"status": "failed", "error_message": "API 连接失败"}
        except Exception as exc:
            status_text.warning(f"轮询异常：{exc}")
            time.sleep(poll_interval)
            continue

        progress = data.get("progress", 0.0)
        status = data.get("status", "unknown")
        message = data.get("progress_message", "")

        progress_bar.progress(progress, text=message)
        status_text.info(f"状态：{status} | 进度：{progress * 100:.0f}%")

        if status == "completed":
            progress_bar.progress(1.0, text="研究完成")
            status_text.success(
                f"研究完成 — 评分：{data.get('score', '-')}，"
                f"评级：{data.get('rating', '-')}，建议：{data.get('action', '-')}"
            )
            return data
        elif status == "failed":
            progress_bar.progress(progress, text="任务失败")
            status_text.error(f"任务失败：{data.get('error_message', '未知错误')}")
            return data
        elif status == "cancelled":
            progress_bar.progress(progress, text="任务已取消")
            status_text.warning("任务已取消")
            return data

        time.sleep(poll_interval)

    status_text.warning("轮询超时（任务可能仍在后台运行，请稍后手动刷新）")
    return {"status": "timeout", "error_message": f"轮询超过 {max_duration} 秒"}


def poll_batch_progress(batch_id: str, poll_interval: float = 1.5,
                        max_duration: float = 900.0) -> dict:
    """轮询批量扫描进度并渲染进度条。

    Returns:
        最终的批量状态 dict
    """
    import requests

    started = time.time()
    status_text = st.empty()
    progress_bar = st.progress(0.0, text="批量扫描中...")

    while time.time() - started < max_duration:
        try:
            resp = requests.get(
                f"{API_BASE}/api/v1/watchlist/scan/{batch_id}", timeout=5
            )
            if resp.status_code >= 400:
                status_text.error(f"查询失败 [{resp.status_code}]")
                time.sleep(poll_interval)
                continue
            data = resp.json()
        except requests.ConnectionError:
            status_text.error("无法连接 API 服务。")
            return {"status": "failed"}
        except Exception as exc:
            status_text.warning(f"轮询异常：{exc}")
            time.sleep(poll_interval)
            continue

        total = data.get("total_items", 0)
        completed = data.get("completed_items", 0)
        failed = data.get("failed_items", 0)
        status = data.get("status", "unknown")
        done = completed + failed

        if total > 0:
            fraction = done / total
        else:
            fraction = 0.0

        progress_bar.progress(
            fraction,
            text=f"{done}/{total} 完成（{failed} 失败）"
        )
        status_text.info(f"状态：{status}")

        if status == "completed":
            progress_bar.progress(1.0, text=f"扫描完成 — {total} 个标的，{failed} 失败")
            status_text.success(f"批量扫描完成 — {completed}/{total} 成功")
            return data

        time.sleep(poll_interval)

    status_text.warning("轮询超时（扫描可能仍在后台运行）")
    return {"status": "timeout", "error_message": f"轮询超过 {max_duration} 秒"}


def submit_research_task(symbol: str, data_source: str = "mock",
                         use_llm: bool = True) -> dict | None:
    """提交研究任务到 FastAPI 并返回 task_id 等元信息。

    Returns:
        {"task_id": str, "status": str, "created_at": str} 或 None
    """
    import requests
    try:
        resp = requests.post(
            f"{API_BASE}/api/v1/research/single",
            json={
                "symbol": symbol,
                "data_source": data_source,
                "use_llm": use_llm,
            },
            timeout=10,
        )
        if resp.status_code == 202:
            return resp.json()
        st.error(f"提交失败 [{resp.status_code}]: {resp.text[:300]}")
        return None
    except requests.ConnectionError:
        st.error("无法连接 API 服务，请确认 FastAPI 已启动（uvicorn apps.api.main:app）")
        return None


def fetch_task_result(task_id: str) -> dict | None:
    """从 API 获取已完成任务的完整研究结果。"""
    import requests
    try:
        resp = requests.get(
            f"{API_BASE}/api/v1/research/{task_id}/result", timeout=15
        )
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None
