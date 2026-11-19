# TaskList AK

Menedżer zadań dla Windows z kalendarzem (widoki **miesiąc / tydzień / dzień**) i przeciąganiem zadań.
Zbudowany tak jak [HarmonogramAK](https://github.com/xthomx/HarmonogramAK): aplikacja okienkowa (Python + pywebview),
lokalny interfejs w `ui/`, wersja EXE budowana przez GitHub Actions i **aktualizacje z GitHub Releases**.

## Funkcje
- **Widoki:** Miesiąc / Tydzień oraz podsumowanie dnia „Zadania na dziś” (podział godzinowy z przypisywaniem zadań do godzin albo sekcje). Klawisze `m`, `w`, `d`, strzałki ←/→; kółko myszy przewija daty (w miesiącu co tydzień); numery tygodni (ISO).
- **Przeciąganie zadań** na inny dzień lub godzinę (krok 15 min), zmiana czasu trwania dolną krawędzią, zadania **wielodniowe** (uchwyt na końcu) i **cykliczne** (seria). Dzień z wieloma zadaniami przewija się w komórce.
- **Układy:** Kafelki (karty, także w miesiącu) lub Siatka (godzinowa); motyw jasny / ciemny; pokaż / ukryj listę zadań pod kalendarzem.
- **Zadania:** priorytety (wysoki pulsuje), status oczekujące / w trakcie / zrobione, postęp 0–100% co 25 (zrobione = 100%), własny kolor, notatki, dymek z opisem po najechaniu, menu prawego przycisku (status, postęp, kolor, przeniesienie, edycja, usunięcie).
- **Osoby** („Nazwisko Imię”) i **filtry** w panelu: osoby (wielokrotny wybór), priorytet, postęp.
- **Przenoszenie:** zaległe → na dziś, zaznaczone → przyszły tydzień, pojedyncze zadanie na przyszły tydzień.
- **Przypomnienia** o zadaniach z godziną: okienko, sygnał dźwiękowy, miganie na pasku zadań, odłożenie o 10 min.
- **Zadanie z maila:** przeciągnij wiadomość z Outlooka (albo plik `.msg` / `.eml`) na kalendarz.
- **Kalendarz lokalny i grupowy:** przyciski Lokalny / Grupowy na górnej belce wybierają, gdzie trafiają nowe zadania; zadania grupowe mają ikonę osób. Plik grupowy (JSON, np. na dysku sieciowym) zawiera tylko zadania grupowe; zmiany kilku osób **scalają się automatycznie** (porównanie trzech wersji, raport zmian i konfliktów), program sprawdza plik co 30 s i działa na kopii, gdy sieć jest niedostępna.
- **Zapis automatyczny:** kopia robocza w `dane\` obok programu, a połączone pliki (Excel z zadaniami lokalnymi, plik grupowy) zapisują się po każdej zmianie; Ctrl+S zapisuje natychmiast. Zapis działa też na folderach bez podmiany plików (np. folder współdzielony VMware). Logi w `logi\`.
- **Excel i JSON:** otwieranie zapamiętywanego pliku Excela, eksport i import osobno dla każdego kalendarza.
- **Jak używać:** wbudowana strona pomocy z opisem wszystkich funkcji i rysunkami (przycisk w lewym dolnym rogu panelu).
- **Aktualizacje:** sprawdzanie przy starcie i przyciskiem; instalacja jednym kliknięciem (pobranie, weryfikacja SHA256, podmiana plików z kopią zapasową i wycofaniem, ponowne uruchomienie). Gdy GitHub ogranicza zapytania, działa zapasowy sposób sprawdzania.

## Uruchomienie
- Gotowa wersja: pobierz `TaskListAK-Windows-x64.zip` z [Releases](https://github.com/xthomx/TaskList_AK/releases), rozpakuj cały folder i uruchom `TaskListAK.exe` (wymagany WebView2 Runtime).
- Ze źródeł: `URUCHOM.bat`. Własny EXE: `ZBUDUJ_EXE.bat`. Szczegóły w `INSTRUKCJA.txt`.
- Interfejs działa też bez Pythona: otwórz `ui/index.html` w przeglądarce (dane w localStorage, bez aktualizacji i bez strony „Jak używać”).

## Wydawanie nowej wersji
1. Zwiększ `APP_VERSION` w `app_version.py` (np. `1.0.1`).
2. Wypchnij na `main` — workflow uruchomi testy, zbuduje EXE i opublikuje Release `v1.0.1`.
3. Zainstalowane programy zobaczą nową wersję i zaproponują aktualizację.
