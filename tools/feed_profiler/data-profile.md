# Kraków — decyzja po sprawdzeniu GTFS-RT

Badanie: 27 września 2026, 15:41–15:51 czasu polskiego, około 10 minut, pobieranie co 30 sekund. Źródła: [ZTP Kraków](https://gtfs.ztp.krakow.pl/), osobno zestawy A, T i M.

**Możemy rozpocząć pilotaż. Najlepszym punktem startowym jest Mobilis (M).** Próba potwierdza dostępność danych i możliwość wyznaczania kandydatów na przyjazd. Nie potwierdza jeszcze dokładności czasów rzeczywistych ani pełnego pokrycia sieci.

| Wynik w próbce | Tramwaje (T) | Autobusy MPK (A) | Mobilis (M) |
| --- | ---: | ---: | ---: |
| Poprawne pliki RT | 66 | 55 | 66 |
| Błędy pobierania według końcowego komunikatu kolektora | 0 | 11 | 0 |
| Zgodność wystąpień trip_id z własnym ZIP | 99,7% | 100% | 100% |
| Zgodność sekwencji VP i podanego stop_id z kursem | 29,3% | 53,0% | 100% |
| Kandydaci na przyjazd z przejścia do STOPPED_AT | 0 | 38 | 158 |
| Kandydaci z GPS do 50 m od przystanku | — | 37/38 | 158/158 |
| Jawne odwołania CANCELED | 0 | 0 | 0 |

Liczby błędów pobierania pochodzą z zanotowanego podsumowania terminala.
Zachowane raporty wskazują brak `errors.jsonl` dla tej kolekcji, dlatego samymi
plikami ZIP/PB nie można niezależnie potwierdzić liczby ani przyczyn błędów.

Kandydat oznacza przejście IN_TRANSIT_TO/INCOMING_AT → STOPPED_AT dla tej samej sekwencji przystanku, ze świeżymi timestampami i zgodnością z rozkładem. Zero dla tramwajów wynika z ograniczeń tej metody przy niespójnej sekwencji; nie oznacza braku przyjazdów. Procenty dotyczą wystąpień w próbkach, a nie unikalnych wykonanych kursów.

## Decyzje dla pilotażu

- **Źródło:** Kraków, początkowo Mobilis. Kolektor obsługuje też A i T, ale wymagają dodatkowej obsługi jakości danych.
- **Przyjazdy:** estymować z historii pozycji i statusu pojazdu, zachowując przedział czasu i jakość estymacji. Dla 158 kandydatów Mobilisu mediana odstępu timestampów wyniosła 28 s, maksimum 38 s. Mediana odległości GPS od przystanku wyniosła 10 m, maksimum 40 m. To test spójności, nie zmierzony błąd estymatora.
- **Opóźnienia:** oddzielać prognozy z TripUpdates od opóźnień wyliczonych na podstawie oszacowanego przyjazdu. Przed wyliczaniem drugich trzeba prawidłowo ustalić datę kursu i połączyć zdarzenie z rozkładem.
- **Czasy TripUpdates:** nie zapisywać arrival.time automatycznie jako potwierdzonego przyjazdu. W Mobilisie 104/105 ponownych obserwacji czasu, który wcześniej był już przeszły, zawierało jego korektę.
- **Odwołania:** przetwarzać jawne CANCELED, ale traktować skuteczność ich wykrywania jako niezweryfikowaną. Nieobecność kursu w feedzie nie oznacza odwołania. W tej próbie nie zaobserwowano CANCELED.

Następna walidacja powinna objąć kilka godzin, następnie pełny dzień, w tym zmianę daty kursu. Dopiero wtedy można oceniać pokrycie przejazdów, stabilność estymacji i rzadkie zdarzenia.

## Materiał źródłowy

- [Raport Mobilis](reports/krakow-M-20260927.md)
- [Raport autobusów MPK](reports/krakow-A-20260927.md)
- [Raport tramwajów](reports/krakow-T-20260927.md)

Surowe ZIP, metadane źródeł i migawki znajdują się lokalnie w ignorowanych przez Git katalogach `data/krakow-{A,M,T}-20260927/`. Zachowano je do odtworzenia wyników. Błędy tej pierwszej kolekcji były raportowane w terminalu; aktualny kolektor zapisuje również `errors.jsonl`.
