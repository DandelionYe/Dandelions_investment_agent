@echo off
REM 强制清除所有形式的代理变量
set HTTP_PROXY=
set HTTPS_PROXY=
set http_proxy=
set https_proxy=
set NO_PROXY=*
set all_proxy=
set ALL_PROXY=

REM 进入项目并激活虚拟环境
cd /d J:\Dandelions_investment_agent
call .venv\Scripts\activate.bat

REM 启动 Claude Code（可自行增补参数）
claude %*