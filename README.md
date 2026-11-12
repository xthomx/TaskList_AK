# TaskList AK

Menedżer zadań dla Windows z kalendarzem (widoki **miesiąc / tydzień / dzień**) i przeciąganiem zadań.
Zbudowany tak jak [HarmonogramAK](https://github.com/xthomx/HarmonogramAK): aplikacja okienkowa (Python + pywebview),
lokalny interfejs w `ui/`, wersja EXE budowana przez GitHub Actions i **aktualizacje z GitHub Releases**.

## Funkcje
- Widoki Miesiąc / Tydzień / Dzień (klawisze `m`, `w`, `d`; strzałki ←/→ zmieniają okres).
- Przeciąganie zadań myszą: na inny dzień (miesiąc) lub dzień i godzinę, krok 15 min (tydzień/dzień); pasek „cały dzień”.
- Zmiana długości zadania dolną krawędzią kafelka. Priorytety, status „wykonane”, notatki.
- **Osoby** (zapis „Nazwisko Imię”): zadania można przypisać do jednej lub kilku osób, filtr osoby w nagłówku.
- **Lista zadań** pod kalendarzem, posortowana w kolejności wykonania.
- **Widok kafelkowy** tygodnia i dnia (kolumna „Zaległe”, karty, szybkie dodawanie, przeciąganie) oraz klasyczna siatka godzinowa — przełącznik w nagłówku.
- **Zadania wielodniowe** (rozciągane myszą lub polem „Do dnia”) i **cykliczne** (seria zadań).
- **Status i postęp:** oczekujące / w trakcie / zrobione (prawy przycisk myszy, 3 ikony) oraz suwak postępu 0–100% co 25; „zrobione” = 100%.
- **Przenoszenie:** zadanie na przyszły tydzień oraz masowo niezakończone na dziś lub na przyszły tydzień (menu „Przenieś”).
- **Zadanie z maila:** przeciągnij wiadomość z Outlooka (albo plik `.msg` / `.eml`) na kalendarz — powstaje zadanie z tematem, nadawcą i treścią w notatkach.
- **Excel z pamięcią pliku:** „Otwórz plik Excela” zapamiętuje plik i wczytuje go automatycznie przy starcie; Ctrl+S zapisuje do niego zmiany (wskaźnik „niezapisane zmiany”). Niezapisanych zmian program nie nadpisuje plikiem. Arkusze „Zadania” i „Osoby”.
- Kopia robocza zapisuje się automatycznie w `%LOCALAPPDATA%TaskListAK	asks.json` (poza folderem programu); eksport/import JSON.
- **Aktualizacje:** sprawdzanie przy starcie i przyciskiem „Sprawdź aktualizacje”; instalacja jednym kliknięciem
  (pobranie, weryfikacja SHA256, podmiana plików z kopią zapasową i wycofaniem, ponowne uruchomienie).

## Uruchomienie
- Gotowa wersja: pobierz `TaskListAK-Windows-x64.zip` z [Releases](https://github.com/xthomx/TaskList_AK/releases), rozpakuj cały folder i uruchom `TaskListAK.exe` (wymagany WebView2 Runtime).
- Ze źródeł: `URUCHOM.bat`. Własny EXE: `ZBUDUJ_EXE.bat`. Szczegóły w `INSTRUKCJA.txt`.
- Interfejs działa też bez Pythona: otwórz `ui/index.html` w przeglądarce (dane w localStorage, bez aktualizacji).

## Wydawanie nowej wersji
1. Zwiększ `APP_VERSION` w `app_version.py` (np. `1.0.1`).
2. Wypchnij na `main` — workflow uruchomi testy, zbuduje EXE i opublikuje Release `v1.0.1`.
3. Zainstalowane programy zobaczą nową wersję i zaproponują aktualizację.
