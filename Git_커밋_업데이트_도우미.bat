@echo off
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion
title Git 커밋·업데이트 도우미

rem 이 BAT 파일이 들어 있는 폴더를 Git 작업 폴더로 사용합니다.
cd /d "%~dp0"

call :CHECK_ENV
if errorlevel 1 goto :END

:MENU
call :GET_BRANCH
if errorlevel 1 goto :END

cls
echo ============================================================
echo                 Git 커밋·업데이트 도우미
echo ============================================================
echo 작업 폴더 : %CD%
echo 현재 브랜치: %BRANCH%
echo.
echo [1] 변경 파일 커밋 후 GitHub에 업로드
echo [2] GitHub의 최신 내용으로 로컬 폴더 업데이트
echo [3] 현재 Git 상태 확인
echo [4] 종료
echo.
choice /C 1234 /N /M "실행할 번호를 선택하세요 [1-4]: "

if errorlevel 4 goto :END
if errorlevel 3 goto :STATUS
if errorlevel 2 goto :PULL
if errorlevel 1 goto :COMMIT_PUSH
goto :MENU

:COMMIT_PUSH
cls
echo ============================================================
echo          변경 파일 등록 → 커밋 → GitHub 업로드
echo ============================================================
echo.

git add -A
if errorlevel 1 goto :FAILED

git diff --cached --quiet
if not errorlevel 1 goto :NO_CHANGES

echo 커밋할 변경 내용:
echo ------------------------------------------------------------
git status --short
echo ------------------------------------------------------------
echo.

set "COMMIT_MSG="
set /P "COMMIT_MSG=커밋 메시지를 입력하세요: "
if not defined COMMIT_MSG set "COMMIT_MSG=Update files"

echo.
echo [1/3] 커밋 중...
git commit -m "%COMMIT_MSG%"
if errorlevel 1 goto :FAILED

echo.
echo [2/3] 원격 저장소 변경 사항 확인 중...
git pull --rebase origin "%BRANCH%"
if errorlevel 1 goto :REBASE_FAILED

echo.
echo [3/3] GitHub에 업로드 중...
git push origin "%BRANCH%"
if errorlevel 1 goto :FAILED

echo.
echo ============================================================
echo 커밋과 업로드가 완료되었습니다.
echo ============================================================
pause
goto :MENU

:NO_CHANGES
echo 변경된 파일이 없어 커밋하지 않았습니다.
echo.
git status
pause
goto :MENU

:PULL
cls
echo ============================================================
echo             GitHub 최신 내용으로 로컬 업데이트
echo ============================================================
echo.

for /F "delims=" %%A in ('git status --porcelain') do goto :LOCAL_CHANGES

git pull --rebase origin "%BRANCH%"
if errorlevel 1 goto :REBASE_FAILED

echo.
echo ============================================================
echo 로컬 폴더가 최신 상태로 업데이트되었습니다.
echo ============================================================
pause
goto :MENU

:LOCAL_CHANGES
echo 로컬에 아직 커밋하지 않은 변경 사항이 있습니다.
echo 데이터 보호를 위해 자동 업데이트를 중단했습니다.
echo.
git status --short
echo.
echo 먼저 메뉴 [1]에서 커밋하거나 변경 사항을 정리한 후 다시 실행하세요.
pause
goto :MENU

:STATUS
cls
echo ============================================================
echo                    현재 Git 상태
echo ============================================================
echo.
git status
echo.
pause
goto :MENU

:CHECK_ENV
where git >nul 2>&1
if errorlevel 1 (
    echo Git이 설치되어 있지 않거나 PATH에 등록되지 않았습니다.
    echo Git for Windows를 먼저 설치하세요.
    pause
    exit /B 1
)

if not exist ".git" (
    echo 현재 폴더는 Git 저장소가 아닙니다.
    echo.
    echo 이 BAT 파일을 .git 폴더가 있는 프로젝트 최상위 폴더에 넣으세요.
    echo 현재 폴더: %CD%
    pause
    exit /B 1
)

git remote get-url origin >nul 2>&1
if errorlevel 1 (
    echo origin 원격 저장소가 연결되어 있지 않습니다.
    echo 먼저 GitHub 저장소를 origin으로 연결해야 합니다.
    pause
    exit /B 1
)

exit /B 0

:GET_BRANCH
set "BRANCH="
for /F "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"

if not defined BRANCH (
    echo 현재 브랜치를 확인할 수 없습니다.
    echo detached HEAD 상태인지 확인하세요.
    pause
    exit /B 1
)

exit /B 0

:REBASE_FAILED
echo.
echo ============================================================
echo 업데이트 과정에서 충돌 또는 오류가 발생했습니다.
echo ============================================================
echo.
git status
echo.
echo 충돌이 표시되면 파일을 수정한 뒤 아래 순서로 진행하세요.
echo   git add -A
echo   git rebase --continue
echo   git push origin %BRANCH%
echo.
echo 리베이스를 취소하려면:
echo   git rebase --abort
echo.
pause
goto :MENU

:FAILED
echo.
echo ============================================================
echo 작업 중 오류가 발생했습니다.
echo ============================================================
git status
echo.
pause
goto :MENU

:END
echo.
echo 종료합니다.
endlocal
