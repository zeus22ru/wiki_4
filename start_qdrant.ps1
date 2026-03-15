# Скрипт для запуска Qdrant в Docker
# Проблема с портами в Windows/Hyper-V: нужна настройка исключений портов

Write-Host "=== Запуск Qdrant в Docker ===" -ForegroundColor Cyan

# Проверяем, запущен ли контейнер
$existing = docker ps -a --filter "name=qdrant-vector-db" --format "{{.ID}}"
if ($existing) {
    Write-Host "Найден существующий контейнер qdrant-vector-db" -ForegroundColor Yellow
    docker rm -f qdrant-vector-db
    Write-Host "Контейнер удалён" -ForegroundColor Green
}

# Пытаемся запустить с портами 6333/6334
try {
    Write-Host "Запуск контейнера Qdrant на портах 6333/6334..." -ForegroundColor Cyan
    docker run -d `
        --name qdrant-vector-db `
        -p 6333:6333 `
        -p 6334:6334 `
        -v qdrant_storage:/qdrant/storage `
        qdrant/qdrant:latest

    Write-Host "Qdrant успешно запущен!" -ForegroundColor Green
    Write-Host "Web UI доступен по адресу: http://localhost:6333/dashboard" -ForegroundColor Cyan
    Write-Host "API доступен по адресу: http://localhost:6333" -ForegroundColor Cyan
    Write-Host "gRPC доступен по адресу: localhost:6334" -ForegroundColor Cyan

} catch {
    Write-Host "Ошибка запуска на портах 6333/6334" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ""
    Write-Host "Проблема: Порты недоступны из-за ограничений Hyper-V" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "=== Варианты решения ===" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "1. Добавить исключения для портов в Windows Firewall:" -ForegroundColor White
    Write-Host "   Запустите PowerShell от имени администратора и выполните:" -ForegroundColor Gray
    Write-Host "   netsh int ipv4 add excludedportrange protocol=tcp startport=6333 numberofports=2" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "2. Использовать порт 6335/6336:" -ForegroundColor White
    Write-Host "   docker run -d --name qdrant-vector-db -p 6335:6333 -p 6336:6334 -v qdrant_storage:/qdrant/storage qdrant/qdrant:latest" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "3. Использовать docker-compose.yml:" -ForegroundColor White
    Write-Host "   docker-compose up -d" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "4. Перезапустить Docker Desktop:" -ForegroundColor White
    Write-Host "   Иногда помогает перезапуск службы Docker" -ForegroundColor Yellow
}