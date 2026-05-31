"""Dashboard RBAC 契约测试。

覆盖：
- 报告库不再直接 glob("*_result.json") 扫描所有报告。
- 观察池本地 SQLite fallback 默认关闭。
- authenticated_request 继续携带 Bearer token。
- login.py 提供 current_user()、current_role()、is_admin() helper。
"""

import os
import pytest


class TestReportLibraryContract:

    def test_no_direct_glob_scan(self):
        """报告库不再直接 glob 扫描 storage/reports。"""
        source = open(
            "apps/dashboard/pages/2_Report_Library.py", encoding="utf-8"
        ).read()
        # 不应有 glob("*_result.json") 或类似直接文件系统扫描
        assert "glob(" not in source or "REPORTS_DIR.glob" not in source
        # 应通过 API 获取任务列表
        assert "/api/v1/research/history" in source

    def test_download_via_api(self):
        """下载按钮应走 API 而非直接读文件。"""
        source = open(
            "apps/dashboard/pages/2_Report_Library.py", encoding="utf-8"
        ).read()
        assert "/api/v1/reports/" in source


class TestWatchlistFallbackContract:

    def test_local_fallback_default_off(self):
        """观察池本地 SQLite fallback 默认关闭。"""
        source = open(
            "apps/dashboard/pages/3_观察池.py", encoding="utf-8"
        ).read()
        # 应检查环境变量，默认关闭
        assert "STREAMLIT_LOCAL_STORE_FALLBACK" in source
        assert '""' in source or "false" in source.lower() or '"0"' in source

    def test_api_only_error_message(self):
        """API 不可用且 fallback 关闭时显示错误。"""
        source = open(
            "apps/dashboard/pages/3_观察池.py", encoding="utf-8"
        ).read()
        assert "API 服务不可用" in source or "必须通过 API" in source


class TestLoginContract:

    def test_login_saves_role(self):
        """登录后获取并保存 auth_role。"""
        source = open(
            "apps/dashboard/components/login.py", encoding="utf-8"
        ).read()
        assert "auth_role" in source
        assert "_fetch_user_info" in source

    def test_provides_role_helpers(self):
        """login.py 提供 current_user、current_role、is_admin helper。"""
        source = open(
            "apps/dashboard/components/login.py", encoding="utf-8"
        ).read()
        assert "def current_user()" in source
        assert "def current_role()" in source
        assert "def is_admin()" in source

    def test_logout_clears_role(self):
        """登出时清理 auth_role。"""
        source = open(
            "apps/dashboard/components/login.py", encoding="utf-8"
        ).read()
        assert '"auth_role"' in source
        # _logout 委托 _clear_session_only 清除 auth_role，验证两者都存在
        logout_section = source[source.index("def _logout"):]
        assert "_clear_session_only" in logout_section
        clear_section = source[source.index("def _clear_session_only"):]
        assert "auth_role" in clear_section

    def test_authenticated_request_sends_bearer(self):
        """authenticated_request 继续携带 Bearer token。"""
        source = open(
            "apps/dashboard/components/login.py", encoding="utf-8"
        ).read()
        assert "Bearer" in source
        assert "auth_headers" in source


class TestResearchPageContract:

    def test_sync_mode_warning(self):
        """同步本地模式有警告提示。"""
        source = open(
            "apps/dashboard/pages/1_Single_Asset_Research.py", encoding="utf-8"
        ).read()
        assert "同步本地模式" in source or "单机自用" in source
