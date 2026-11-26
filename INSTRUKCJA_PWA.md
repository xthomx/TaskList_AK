# TaskList AK na iPhone'a (PWA + OneDrive)

Aplikacja działa w Safari jako strona dodana do ekranu początkowego. Zadania są zapisywane w pamięci telefonu
i (po skonfigurowaniu) synchronizowane z plikami JSON w Twoim OneDrive.

## 1. Rejestracja aplikacji w Microsoft Entra (jednorazowo, ok. 5 minut)

1. Wejdź na <https://entra.microsoft.com> → **Applications → App registrations → New registration**
   (przy koncie prywatnym: <https://portal.azure.com> → *Microsoft Entra ID* → *App registrations*).
2. Nazwa: `TaskList AK`. **Supported account types**: wybierz wariant z kontami osobistymi i/lub organizacyjnymi
   (zależnie od tego, gdzie masz OneDrive). Konto firmowe może wymagać zgody administratora.
3. **Redirect URI**: platforma **Single-page application (SPA)**, adres: `https://xthomx.github.io/TaskList_AK/`
   (dokładnie taki, z ukośnikiem na końcu; ten sam adres pokaże okno „OneDrive" w aplikacji).
4. Po utworzeniu skopiuj **Application (client) ID**.
5. **API permissions → Add → Microsoft Graph → Delegated**: `Files.ReadWrite` (offline_access jest dodawane automatycznie).

## 2. Instalacja na iPhonie

1. Otwórz w **Safari** adres `https://xthomx.github.io/TaskList_AK/`.
2. Udostępnij → **Dodaj do ekranu początkowego**.
3. Uruchom aplikację z ikony → ☰ → **OneDrive** → wklej Client ID → **Zaloguj**.

## 3. Pliki w OneDrive

* Kalendarz **grupowy**: `TaskListAK/grupowy.json` — ten sam format i to samo scalanie zmian co w programie na Windows.
  Na komputerze wskaż ten plik jako plik grupowy (Pliki → Grupowy → Otwórz), używając folderu zsynchronizowanego z OneDrive
  (np. `C:\Users\...\OneDrive\TaskListAK\grupowy.json`).
* Kalendarz **prywatny**: `TaskListAK/prywatny.json` (włączony domyślnie) — Twoje zadania na wielu urządzeniach.
  Na komputerze: Pliki → Kalendarz prywatny → „Połącz z plikiem prywatnym w chmurze…" (lub „Utwórz…") i wskaż
  `...\OneDrive\TaskListAK\prywatny.json`. Lokalizację możesz zmienić w dowolnej chwili (Odłącz i połącz z innym plikiem).
  Excel (jeśli go używasz) działa jak dotąd, niezależnie od tego pliku.

## Ograniczenia

* Przypomnienia (okienko + dźwięk) działają tylko, gdy aplikacja jest otwarta (iOS nie pozwala stronie dzwonić w tle).
* Token logowania w aplikacjach typu SPA wygasa po 24 h — wtedy trzeba kliknąć **Zaloguj** ponownie (dane nie giną).
* Wczytywanie plików .msg/.eml i Excela działa tylko w programie na Windows.
