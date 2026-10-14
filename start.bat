@echo off
REM =====================================================================
REM  Запуск веб-сервиса «Парки и сады Петроградского района»
REM
REM  Требования:
REM    * Python 3.10+ и установленные зависимости:  pip install -r requirements.txt
REM    * PostgreSQL 14+ с расширениями postgis, cube, pg_trgm
REM      (база данных уже наполнена — см. README, раздел «Данные»)
REM    * [Для AI-поиска] Ollama с моделью qwen2.5:3b
REM      (https://ollama.com  ->  ollama pull qwen2.5:3b)
REM      Без Ollama сервис работает в режиме правил (GIS-search) — это норма.
REM
REM  После запуска откройте:  http://127.0.0.1:8000
REM  Документация API:         http://127.0.0.1:8000/docs
REM =====================================================================
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
  echo [!] Виртуальное окружение не найдено. Создаю и ставлю зависимости...
  python -m venv venv || goto :error
  venv\Scripts\python -m pip install --upgrade pip
  venv\Scripts\pip install -r requirements.txt || goto :error
)

echo [.] Проверяю доступность базы данных...
pushd backend
..\venv\Scripts\python -c "import sys; sys.path.insert(0,'.'); from app.database import db_health; h=db_health(); print('БД:', ('OK, парков=%s' % h['parks']) if h['ok'] else ('НЕДОСТУПНА — ' + str(h['error'])))"
popd

echo [.] Проверяю AI-модель (Ollama)...
powershell -NoProfile -Command "if ((Test-NetConnection -ComputerName 127.0.0.1 -Port 11434 -WarningAction SilentlyContinue).TcpTestSucceeded) { echo 'AI: Ollama запущен (порт 11434)' } else { echo 'AI: Ollama не найден — включён режим правил (GIS-search).' }"

echo [.] Запускаю сервер: http://127.0.0.1:8000
cd backend
..\venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
goto :eof

:error
echo [!] Ошибка: проверьте Python 3.10+ и доступность PostgreSQL.
pause
exit /b 1
