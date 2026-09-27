# 001 — Start with Kraków Mobilis

Status: accepted  
Date: 2026-09-27

## Context

Wcześniej analizowano Rzeszów. W badanej próbce feedu RT brakowało
`arrival.time` i jawnego `current_status`, a `arrival.delay` oraz
`departure.delay` miały jednakowe wartości. Ograniczało to możliwość
rozróżniania przyjazdów i odjazdów oraz szacowania momentu przyjazdu.
Wykryte zdarzenia nie stanowiły potwierdzonych przyjazdów.

Następnie zbadano krakowskie feedy A (autobusy MPK), M (Mobilis) i T (tramwaje).
W około dziesięciominutowej próbie M miał pełne timestampy TripUpdates
oraz spójne identyfikatory przystanków i sekwencje VehiclePositions.
Znaleziono 158 kandydatów przejścia do `STOPPED_AT`, wszystkie z GPS
w odległości do 50 m od przystanku. To podstawa do dalszego badania
przedziałów przyjazdu; dokładność metody pozostaje niezweryfikowana.

Porównanie: [wyniki profilowania A/M/T](../../tools/feed_profiler/data-profile.md).

## Decision

Pierwszy przepływ danych budujemy dla Krakowa, zaczynając od `krakow_ztp_m`.
Rozważone źródła to Rzeszów oraz krakowskie A/M/T. M wybieramy ze względu
na spójność pól w badanej próbie. Dodanie A i T odkładamy do rozszerzenia.

## Consequences

- Identyfikatory od początku uwzględniają `source_id`.
- Wybór M wymaga potwierdzenia dłuższą obserwacją, w tym kursów nocnych.
- `arrival.time` zachowujemy jako czas raportowany przez dostawcę;
  sama obecność pola nie rozstrzyga, czy jest prognozą, czy pomiarem.
- Ze zmian stanów pojazdu możemy wyznaczać kandydatów przedziałów przyjazdu.
  Osobnej walidacji wymagają timestampy, GPS i sposób raportowania stanów.
