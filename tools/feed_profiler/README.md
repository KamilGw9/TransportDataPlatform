# Kraków ZTP — profiler GTFS i GTFS-RT

Pobiera rozkład i trzy osobne strumienie RT z [serwera ZTP Kraków](https://gtfs.ztp.krakow.pl/). Sprawdza zgodność identyfikatorów, świeżość danych, czasy i opóźnienia, anulowania oraz przydatność historii do szacowania faktycznych przyjazdów.

| `--network` | Zakres | Rozkład | Strumienie RT |
| --- | --- | --- | --- |
| `T` (domyślny) | Tramwaje | `GTFS_KRK_T.zip` | `VehiclePositions_T.pb`, `TripUpdates_T.pb`, `ServiceAlerts_T.pb` |
| `A` | Autobusy MPK | `GTFS_KRK_A.zip` | analogiczne pliki z `_A` |
| `M` | Mobilis | `GTFS_KRK_M.zip` | analogiczne pliki z `_M` |

Każdy zestaw analizujemy względem własnego ZIP; identyfikatorów z różnych zestawów nie należy łączyć bez przestrzeni nazw.

Z katalogu głównego repozytorium przygotuj środowisko:

```bash
python3 -m venv venv
venv/bin/pip install -r tools/feed_profiler/requirements.txt
```

Pierwszym źródłem projektu jest Mobilis; wybierz go jawnie przez `--network M`
(domyślnym wyborem CLI pozostaje T):

```bash
venv/bin/python tools/feed_profiler/profiler.py collect --network M --hours 4 --interval 30 --report-after
```

Bez `--output` każde uruchomienie tworzy nowy katalog
`tools/feed_profiler/data/krakow-<zestaw>-<czas UTC>/`. `--once` pobiera jeden
cykl VP, TU i Alerts dla wybranego zestawu. Dodatkowe badanie A lub T można
uruchomić osobno, zmieniając `--network`. Kolektor pracuje w bieżącym terminalu;
nie ma jeszcze konfiguracji usługi zapewniającej automatyczny restart.

Raport można wygenerować w trakcie zbierania:

```bash
venv/bin/python tools/feed_profiler/profiler.py report --input tools/feed_profiler/data/krakow-M-20260927
venv/bin/python -m unittest discover -s tools/feed_profiler -v
```

Przykład `report` używa lokalnej kolekcji z 27 września. W nowym checkoutcie
podaj katalog utworzony przez własne uruchomienie `collect`; surowe dane
nie są częścią repozytorium. Testy korzystają z danych syntetycznych i nie
wymagają dostępu do sieci.

`--report-after` i `report` zapisują `data-profile.md` wewnątrz katalogu danej kolekcji. `report --output <plik>` wybiera inną ścieżkę. Podsumowanie badania jest w [data-profile.md](data-profile.md), a raporty do zachowania w Git — w `reports/`.

Własne źródła wymagają równoczesnego podania `--gtfs-url` oraz `--rt-url` (powtarzanego dla każdego strumienia); opcjonalne `--label` opisuje raport. Ponowienie z tym samym `--output` dopisuje próbki tylko przy zgodnych źródłach. Przy nowej wersji rozkładu należy użyć nowego katalogu.

Surowe dane w ignorowanym przez Git `data/` obejmują ZIP, jego hash i źródła w `sources.json`, osobne `samples/0`, `samples/1`, `samples/2` oraz błędy pobierania w `errors.jsonl`. Numery strumieni odpowiadają kolejności `rt_urls` w metadanych. Błąd jednego źródła nie przerywa pobierania pozostałych. Kolekcje sprzed dodania dziennika wymagają sprawdzenia logu terminala.

## Ograniczenia profilera

To narzędzie do wstępnego badania źródła. PB zapisuje dopiero po poprawnym
dekodowaniu; błędna odpowiedź nie jest zachowywana jako RAW. `errors.jsonl`
obejmuje błędy pętli RT, ale nie początkowego pobrania ZIP. Nie ma pełnego
rejestru prób HTTP, automatycznego retry ani okresowego pobierania nowych
wersji rozkładu.

Dopasowanie do ZIP sprawdza identyfikatory, nie aktywność kursu według kalendarza.
Przy braku `start_date` historia używa daty lokalnej do grupowania obserwacji.
Obliczenia czasu z rozkładu wymagają dopracowania dla zmiany czasu (DST);
obecne wyniki nie weryfikują poprawności kursów nocnych ani dnia kursowania.

Raport liczy wystąpienia w próbkach, nie unikalne wykonane przejazdy. Czas `arrival.time` w przeszłości nie potwierdza actual arrival — sprawdzamy również jego późniejsze korekty. Kandydatów na przedział przyjazdu szukamy w świeżych, dopasowanych do ZIP przejściach `IN_TRANSIT_TO/INCOMING_AT → STOPPED_AT`. To nadal wymaga walidacji względem GPS i zachowania wydawcy. Brak kursu w feedzie nie potwierdza odwołania. Krótka próbka nie pozwala ocenić pełnego pokrycia sieci ani rzadkich zdarzeń; docelowa walidacja wymaga co najmniej kilku godzin, następnie całego dnia.
