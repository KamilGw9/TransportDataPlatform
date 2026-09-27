# Stan projektu

Ostatnia aktualizacja: 2026-09-27.

- Bieżący etap: 0 — rozpoznanie repozytorium i wybór źródła; przegląd wykonany.
- Istnieją: profiler GTFS/GTFS-RT, jego testy oraz [raporty A/M/T](../tools/feed_profiler/data-profile.md).
- Dane lokalne: ZIP i PB w `tools/feed_profiler/data/` (poza Git).
- Weryfikacja: hashe ZIP zgodne z `sources.json` i zachowanymi raportami;
  liczba PB: A=55, M=66, T=66.
- Odtworzenie raportów A/M/T z lokalnych ZIP/PB: wyniki identyczne z zapisanymi
  raportami po pominięciu czasu wygenerowania.
- Testy: `venv/bin/python -m unittest discover -s tools/feed_profiler -v`
  — 5 testów zakończonych powodzeniem, bez pobierania danych z sieci.
- Pierwsze źródło: `krakow_ztp_m` — autobusy Mobilis;
  [uzasadnienie zmiany miasta i wyboru feedu](adr/001-krakow-m-first.md).
- Brakuje: szkieletu aplikacji Python, lockfile, CI oraz konfiguracji
  PostgreSQL i MinIO w repozytorium.
- Ograniczenia: profiler służy do wstępnego badania danych; nie realizuje jeszcze
  pełnej archiwizacji RAW ani rejestru wszystkich prób HTTP. Krótka próbka
  nie weryfikuje zachowania w nocy i podczas zmiany czasu.
- Otwarte kwestie: dłuższa obserwacja M, zgodność time/delay, ustalanie dnia
  kursowania, interpretacja stanów pojazdu i dokładność estymacji przyjazdów.
- Następne zadanie: etap 1 — odtwarzalne środowisko Python i minimalne CLI.
