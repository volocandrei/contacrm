# ADR-010 — Contorul de încercări, împărțit de toate instanțele

**Status:** Accepted · **Date:** 2026-09-09

## Context

Limitarea încercărilor de autentificare exista și funcționa: `FixedWindowLimiter`
numără eșecurile per cheie, într-o fereastră de un minut, cu contorul în memoria
procesului. Modulul își spunea singur limita, din prima zi:

> Contorul stă în proces. Două procese de API înseamnă două contoare, iar pe o
> platformă care pornește un proces per cerere nu limitează nimic.

Atunci asta era o notă corectă despre o instalare pe server. Între timp ținta de
deploy a devenit o platformă serverless — adică exact cazul din propoziția aceea.

Și este mai rău decât „nu limitează". Serverless-ul **pornește instanțe noi când
crește traficul**, iar traficul care crește brusc pe ruta de autentificare este
chiar cineva care încearcă parole una după alta. Cu cât se apasă mai tare, cu atât
contorul se împarte în mai multe bucăți: protecția slăbea singură, în clipa în care
era nevoie de ea.

Aceeași problemă atinge alte două contoare: cel al asistentului — singurul plafon
de cheltuială către un API plătit — și cel al portalului clientului.

Modulul original s-a născut din constatarea că `RATE_LIMIT_PER_MINUTE` exista în
configurare fără să-l citească nimeni, și din propoziția: *o variabilă care promite
o protecție inexistentă este mai rea decât absența ei.* Un contor per proces, pe o
platformă fără procese stabile, promite la fel de mult.

## Decizie

**Contorul stă într-un rând de bază de date** (`rate_limit_windows`), împărțit de
toate instanțele. Aceleași două operații ca înainte — `blocked` înaintea încercării,
`record` numai după un eșec — aceleași praguri, aceleași chei.

**Nu Redis.** Nu pentru că ar fi interzis, ci pentru că nu este nevoie: fereastra
este de un minut, cheile sunt puține, iar scrierea se face **numai la eșec** — o
autentificare reușită nu atinge tabelul. Baza este oricum singurul lucru pe care
instanțele îl împart, la fel ca în cazul semnului de viață al workerului
([ADR-003](ADR-003-async-processing.md) urmează același raționament pentru coadă).
Un serviciu în plus ar fi însemnat încă un lucru de provizionat, de monitorizat și
de restaurat, pentru un contor de un minut.

**Tranzacție proprie, nu a cererii.** Refuzul la autentificare se ridică drept
eroare de aplicație, iar `CommittingRoute` nu confirmă tranzacția când ruta ridică
ceva. Un eșec numărat în sesiunea cererii s-ar fi dat înapoi odată cu ea — adică
exact încercările care trebuie ținute minte s-ar fi șters singure.

**Lasă să treacă dacă baza nu răspunde.** Un refuz acolo ar transforma o clipire a
bazei într-o pană de autentificare pentru tot cabinetul. Pasul următor are oricum
nevoie de bază și va eșua cu eroarea potrivită.

**Ferestrele vechi se șterg la fiecare tur de worker.** Altfel tabelul ar crește cu
un rând per adresă care a greșit vreodată o parolă.

`FixedWindowLimiter` **rămâne** în `app/core/rate_limit.py`, cu testele lui: este
implementarea de referință pentru fereastra fixă și nu are dependențe. Ce s-a
schimbat este cine îl folosește.

## Consecințe

- O interogare în plus la fiecare încercare de autentificare, și o scriere la
  fiecare eșec. Autentificarea atinge oricum baza imediat după.
- Limita este acum reală și pe mai multe instanțe, inclusiv pe serverul cu două
  containere — unde până acum era, tăcut, dublă.
- **Nu înlocuiește limitarea de la marginea rețelei.** Un atac distribuit, cu o
  adresă nouă la fiecare încercare, trece pe lângă orice contor per cheie; acela se
  oprește la firewall. Ce apără aici este cazul obișnuit: multe parole pe un cont,
  sau o parolă pe multe conturi.
- Un test nou pornește **două** obiecte limitator, ca două instanțe de API, și cere
  să numere în același loc. Detaliul care spune de ce defectul nu se vedea: cu
  contorul per instanță, toate testele existente treceau — foloseau un singur
  obiect, deci întrebau mereu aceeași memorie.
