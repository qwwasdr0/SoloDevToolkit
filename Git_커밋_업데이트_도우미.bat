```bat
@echo off
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion
title Git 커밋 업데이트 도우미

rem ============================================================
rem 설정
rem ============================================================

set "SCRIPT_DIR=%~dp0"
set "REPO_ROOT="
set "BRANCH="
set "EXCLUDE_FILE="
set "COMMIT_MSG="

rem BAT 파일이 있는 폴더로 이동
cd /d "%SCRIPT_DIR%"

if errorlevel 1 goto ERROR_SCRIPT_FOLDER


rem ============================================================
rem Git 실행 가능 여부 확인
rem ============================================================

where git >nul 2>&1

if errorlevel 1 goto ERROR_NO_GIT


rem ============================================================
rem Git 저장소 최상위 폴더 확인
rem ============================================================

for /f "delims=" %%I in ('git rev-parse --show-toplevel 2^>nul') do (
    set "REPO_ROOT=%%I"
)

if not defined REPO_ROOT goto ERROR_NO_REPO

cd /d "%REPO_ROOT%"

if errorlevel 1 goto ERROR_REPO_FOLDER


rem ============================================================
rem origin 원격 저장소 확인
rem ============================================================

git remote get-url origin >nul 2>&1

if errorlevel 1 goto ERROR_NO_ORIGIN


rem ============================================================
rem BAT 파일 자체를 로컬 커밋 대상에서 제외
rem .gitignore가 아니라 .git/info/exclude에 등록
rem ============================================================

call :REGISTER_SELF_IGNORE


rem ============================================================
rem 메인 메뉴
rem ============================================================

goto MENU


:MENU
call :GET_BRANCH

if errorlevel 1 goto ERROR_NO_BRANCH

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

choice /C 1234 /N /M "실행할 번호를 선택하세요 [1-4]: "

if errorlevel 4 goto END
if errorlevel 3 goto STATUS
if errorlevel 2 goto PULL
if errorlevel 1 goto COMMIT_PUSH

goto MENU


rem ============================================================
rem 1. 커밋 후 GitHub 업로드
rem ============================================================

:COMMIT_PUSH
cls
echo ============================================================
echo            변경 파일 커밋 후 GitHub 업로드
echo ============================================================
echo.

echo [1/4] 변경 파일을 커밋 대상으로 등록하는 중...
git add -A

if errorlevel 1 goto GIT_FAILED


rem 스테이징된 변경 파일이 있는지 확인
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
echo [3/4] GitHub 최신 내용을 확인하는 중...
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


rem ============================================================
rem 2. GitHub 최신 내용으로 업데이트
rem ============================================================

:PULL
cls
echo ============================================================
echo             GitHub 최신 내용으로 업데이트
echo ============================================================
echo.

rem 커밋하지 않은 로컬 변경 사항 확인
git status --porcelain | findstr /R /C:"." >nul

if not errorlevel 1 goto LOCAL_CHANGES


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
echo 먼저 메뉴 [1]에서 변경 내용을 커밋하고 업로드하세요.
echo.
pause
goto MENU


rem ============================================================
rem 3. Git 상태 확인
rem ============================================================

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


rem ============================================================
rem 현재 브랜치 확인
rem ============================================================

:GET_BRANCH
set "BRANCH="

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do (
    set "BRANCH=%%B"
)

if not defined BRANCH exit /b 1

exit /b 0


rem ============================================================
rem 현재 BAT 파일을 .git/info/exclude에 자동 등록
rem ============================================================

:REGISTER_SELF_IGNORE
set "EXCLUDE_FILE="

for /f "delims=" %%I in ('git rev-parse --git-path info/exclude 2^>nul') do (
    set "EXCLUDE_FILE=%%I"
)

if not defined EXCLUDE_FILE exit /b 0

findstr /X /L /C:"%~nx0" "%EXCLUDE_FILE%" >nul 2>&1

if not errorlevel 1 exit /b 0

>>"%EXCLUDE_FILE%" echo %~nx0

exit /b 0


rem ============================================================
rem Rebase 또는 Pull 오류
rem ============================================================

:REBASE_FAILED
echo.
echo ============================================================
echo Pull 또는 Rebase 과정에서 오류가 발생했습니다.
echo ============================================================
echo.

git status

echo.
echo 충돌 작업을 취소하려면 다음 명령을 실행하세요.
echo.
echo   git rebase --abort
echo.
echo 충돌 파일을 해결한 뒤 다음 명령을 실행하세요.
echo.
echo   git add -A
echo   git rebase --continue
echo   git push origin %BRANCH%
echo.
pause
goto MENU


rem ============================================================
rem 일반 Git 오류
rem ============================================================

:GIT_FAILED
echo.
echo ============================================================
echo Git 명령 실행 중 오류가 발생했습니다.
echo ============================================================
echo.

git status

echo.
echo 위에 표시된 오류 내용을 확인하세요.
echo.
pause
goto MENU


rem ============================================================
rem 시작 단계 오류
rem ============================================================

:ERROR_SCRIPT_FOLDER
echo.
echo [오류] BAT 파일이 있는 폴더로 이동하지 못했습니다.
echo BAT 위치: %SCRIPT_DIR%
goto FATAL_ERROR


:ERROR_NO_GIT
echo.
echo [오류] Git을 찾을 수 없습니다.
echo Git for Windows 설치 또는 PATH 설정을 확인하세요.
goto FATAL_ERROR


:ERROR_NO_REPO
echo.
echo [오류] 현재 위치에서 Git 저장소를 찾지 못했습니다.
echo.
echo 이 BAT 파일을 Git 프로젝트 폴더 안에 넣으세요.
echo 현재 위치: %CD%
goto FATAL_ERROR


:ERROR_REPO_FOLDER
echo.
echo [오류] Git 저장소 폴더로 이동하지 못했습니다.
echo 저장소 위치: %REPO_ROOT%
goto FATAL_ERROR


:ERROR_NO_ORIGIN
echo.
echo [오류] origin 원격 저장소가 연결되어 있지 않습니다.
echo.
echo 현재 원격 저장소 정보:
git remote -v
goto FATAL_ERROR


:ERROR_NO_BRANCH
echo.
echo [오류] 현재 Git 브랜치를 확인할 수 없습니다.
echo detached HEAD 상태인지 확인하세요.
goto FATAL_ERROR


:FATAL_ERROR
echo.
echo ============================================================
echo 실행을 계속할 수 없습니다.
echo 위 오류 내용을 확인하세요.
echo ============================================================
echo.

pause
goto END


rem ============================================================
rem 종료
rem ============================================================

:END
echo.
echo Git 도우미를 종료합니다.
echo.

endlocal
exit /b 0
```
