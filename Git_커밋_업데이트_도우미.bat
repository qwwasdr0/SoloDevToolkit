@echo off
if /I "%~1"=="__INNER__" goto MAIN

rem 현재 창이 닫혀도 내부 CMD 창은 열린 상태로 유지합니다.
"%ComSpec%" /D /K ""%~f0" __INNER__"
exit /b


:MAIN
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion
title Git 커밋 업데이트 도우미

cd /d "%~dp0"

echo.
echo ============================================================
echo              Git 커밋 업데이트 도우미 시작
echo ============================================================
echo BAT 위치: %CD%
echo.

where git >nul 2>&1
if errorlevel 1 goto ERROR_NO_GIT

set "REPO_ROOT="
for /f "delims=" %%I in ('git rev-parse --show-toplevel 2^>nul') do set "REPO_ROOT=%%I"

if not defined REPO_ROOT goto ERROR_NO_REPO

cd /d "%REPO_ROOT%"
if errorlevel 1 goto ERROR_CD

git remote get-url origin >nul 2>&1
if errorlevel 1 goto ERROR_NO_ORIGIN

rem 현재 BAT 파일을 로컬 Git 제외 목록에 자동 등록합니다.
set "EXCLUDE_FILE="
for /f "delims=" %%I in ('git rev-parse --git-path info/exclude 2^>nul') do set "EXCLUDE_FILE=%%I"

if defined EXCLUDE_FILE (
    findstr /x /l /c:"%~nx0" "%EXCLUDE_FILE%" >nul 2>&1
    if errorlevel 1 echo %~nx0>>"%EXCLUDE_FILE%"
)

goto MENU


:MENU
set "BRANCH="
for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"

if not defined BRANCH goto ERROR_NO_BRANCH

cls
echo ============================================================
echo                Git 커밋 업데이트 도우미
echo ============================================================
echo 작업 폴더 : %CD%
echo 현재 브랜치: %BRANCH%
echo.
echo [1] 변경 파일 커밋 후 GitHub에 업로드
echo [2] GitHub 최신 내용으로 로컬 폴더 업데이트
echo [3] 현재 Git 상태 확인
echo [4] 종료
echo.

set "MENU_NO="
set /p "MENU_NO=실행할 번호를 입력하세요 [1-4]: "

if "%MENU_NO%"=="1" goto COMMIT_PUSH
if "%MENU_NO%"=="2" goto PULL
if "%MENU_NO%"=="3" goto STATUS
if "%MENU_NO%"=="4" goto END

echo.
echo 1부터 4까지의 번호를 입력하세요.
pause
goto MENU


:COMMIT_PUSH
cls
echo ============================================================
echo            변경 파일 커밋 후 GitHub 업로드
echo ============================================================
echo.

echo [1/4] 변경 파일을 등록하는 중...
git add -A
if errorlevel 1 goto GIT_FAILED

git diff --cached --quiet
if errorlevel 2 goto GIT_FAILED
if not errorlevel 1 goto NO_CHANGES

echo.
echo 커밋할 변경 내용:
echo ------------------------------------------------------------
git status --short
echo ------------------------------------------------------------
echo.

set "COMMIT_MSG="
set /p "COMMIT_MSG=커밋 메시지를 입력하세요: "
if not defined COMMIT_MSG set "COMMIT_MSG=파일 업데이트"

echo.
echo [2/4] 로컬 커밋을 생성하는 중...
git commit -m "%COMMIT_MSG%"
if errorlevel 1 goto GIT_FAILED

echo.
echo [3/4] GitHub 최신 변경 내용을 받는 중...
git pull --rebase origin "%BRANCH%"
if errorlevel 1 goto REBASE_FAILED

echo.
echo [4/4] GitHub에 업로드하는 중...
git push origin "%BRANCH%"
if errorlevel 1 goto GIT_FAILED

echo.
echo ============================================================
echo 커밋과 GitHub 업로드가 완료되었습니다.
echo ============================================================
echo.
pause
goto MENU


:NO_CHANGES
echo.
echo 변경된 파일이 없어 커밋하지 않았습니다.
echo.
git status
echo.
pause
goto MENU


:PULL
cls
echo ============================================================
echo             GitHub 최신 내용으로 업데이트
echo ============================================================
echo.

set "HAS_CHANGES="
for /f "delims=" %%A in ('git status --porcelain 2^>nul') do set "HAS_CHANGES=1"

if defined HAS_CHANGES goto LOCAL_CHANGES

echo GitHub에서 최신 변경 내용을 받는 중...
echo.
git pull --rebase origin "%BRANCH%"
if errorlevel 1 goto REBASE_FAILED

echo.
echo ============================================================
echo 로컬 폴더가 최신 상태로 업데이트되었습니다.
echo ============================================================
echo.
pause
goto MENU


:LOCAL_CHANGES
echo 아직 커밋하지 않은 로컬 변경 사항이 있습니다.
echo 파일 보호를 위해 업데이트를 중단했습니다.
echo.
git status --short
echo.
echo 먼저 메뉴 [1]에서 커밋하고 업로드하세요.
echo.
pause
goto MENU


:STATUS
cls
echo ============================================================
echo                    현재 Git 상태
echo ============================================================
echo.
git status
echo.
pause
goto MENU


:REBASE_FAILED
echo.
echo ============================================================
echo Pull 또는 Rebase 과정에서 오류가 발생했습니다.
echo ============================================================
echo.
git status
echo.
echo 작업을 취소하려면 다음 명령을 실행하세요.
echo   git rebase --abort
echo.
echo 충돌을 해결한 뒤 다음 명령을 실행하세요.
echo   git add -A
echo   git rebase --continue
echo   git push origin %BRANCH%
echo.
pause
goto MENU


:GIT_FAILED
echo.
echo ============================================================
echo Git 작업 중 오류가 발생했습니다.
echo ============================================================
echo.
git status
echo.
pause
goto MENU


:ERROR_NO_GIT
echo [오류] Git을 찾을 수 없습니다.
echo Git for Windows 설치 또는 PATH 설정을 확인하세요.
goto STOP


:ERROR_NO_REPO
echo [오류] 현재 BAT 위치에서 Git 저장소를 찾지 못했습니다.
echo 이 파일을 Git 프로젝트 폴더 안에 넣으세요.
goto STOP


:ERROR_CD
echo [오류] Git 저장소 폴더로 이동하지 못했습니다.
echo 저장소 위치: %REPO_ROOT%
goto STOP


:ERROR_NO_ORIGIN
echo [오류] origin 원격 저장소가 연결되어 있지 않습니다.
goto STOP


:ERROR_NO_BRANCH
echo [오류] 현재 Git 브랜치를 확인할 수 없습니다.
goto STOP


:STOP
echo.
echo 오류 내용을 확인하세요.
echo 이 창은 자동으로 닫히지 않습니다.
echo.
pause
goto END


:END
echo.
echo Git 도우미 실행을 종료했습니다.
echo 창을 닫으려면 오른쪽 위 X를 누르거나 exit를 입력하세요.
echo.
endlocal
exit /b
