# Plan projektu

Platforma danych transportu miejskiego dla Krakowa. Celem jest gromadzenie
historii GTFS i GTFS-Realtime oraz udostępnianie analiz prognozowanych opóźnień,
pokrycia kursów danymi RT i jakości źródeł.

## Pierwszy zakres

Zaczynamy od autobusów Mobilis (`krakow_ztp_m`). Pierwszy działający przepływ
obejmie pobranie rozkładu i migawek RT, zachowanie oryginalnych danych,
normalizację, zapytania SQL oraz podstawowy dashboard.

## Kolejność prac

1. Przygotować odtwarzalne środowisko Python, minimalne CLI, testy i CI.
2. Uruchomić lokalnie PostgreSQL i MinIO z trwałym zapisem danych.
3. Zbudować archiwizację GTFS/RT z rejestrem pobrań i wydłużyć obserwację Mobilisu.
4. Wdrożyć walidację, dopasowanie RT do rozkładu i podstawowe modele analityczne.
5. Udostępnić dashboard prognozowanych opóźnień, pokrycia i świeżości danych.

Po pierwszym działającym przepływie planowane są orkiestracja Airflow,
przetwarzanie strumieniowe Kafka, historia RT w ClickHouse oraz monitoring
i odtwarzanie wyników z archiwum. Pogoda, feedy A/T i AWS to dalsze rozszerzenia.

## Założenia

- Zachowujemy oryginalne dane, aby móc ponownie przeliczać wyniki.
- Rozróżniamy prognozowany czas przyjazdu i przedział szacowany ze stanów pojazdu.
- Dokładność szacowania przyjazdów wymaga osobnej walidacji.
- Technologie i źródła dodajemy etapami; powyższa lista opisuje planowane prace.

Aktualne wykonanie opisuje [status projektu](project-status.md),
a wybór źródła — [ADR 001](adr/001-krakow-m-first.md).
