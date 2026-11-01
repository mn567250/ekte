# Se arrivi da zing

> [🇬🇧 English](../../../guide/migrating-from-zing.md) · [🇨🇳 中文](../../zh-CN/guide/migrating-from-zing.md) · [🇫🇷 Français](../../fr/guide/migrating-from-zing.md) · [🇪🇸 Español](../../es/guide/migrating-from-zing.md) · [🇵🇹 Português](../../pt/guide/migrating-from-zing.md) · **🇮🇹 Italiano** · [🇩🇪 Deutsch](../../de/guide/migrating-from-zing.md) · [🇳🇴 Norsk](../../nb/guide/migrating-from-zing.md)

ekte prosegue [zing](https://github.com/cenbonew/zing) (ultima versione: 0.11.0)
con un nome nuovo. Cosa cambia per un'installazione esistente:

- **Pacchetto e comando.** `pip install ekte` (prima `zing-audit`), il comando
  `ekte` (prima `zing`), il pacchetto Python `ekte`. Gli extra mantengono il
  loro nome, ad es. `pip install 'ekte[web]'`. I due pacchetti non condividono
  né comando né modulo, quindi `zing-audit` può restare installato accanto a
  ekte.
- **Variabili d'ambiente.** `EKTE_*` sostituisce `ZING_*` (`EKTE_DATA_DIR`,
  `EKTE_SECRET_KEY`, `EKTE_HOST`, …). Una vecchia variabile `ZING_*` funziona
  ancora finché il suo nome `EKTE_*` non è impostato; ekte la segnala una volta
  su stderr.
- **Directory dei dati.** Al primo avvio ekte copia `~/.zing` in `~/.ekte`
  (cronologia, monitor, base di conoscenza) se `~/.ekte` non esiste ancora, e da
  quel momento lavora solo con `~/.ekte`. `~/.zing` resta com'è, per zing se è
  ancora in uso; eliminalo tu quando non ti serve più. Una directory impostata
  con `EKTE_DATA_DIR`, `ZING_DATA_DIR` o `--data-dir` viene usata così com'è.
- **Interfaccia web.** Lingua, tema e filtri e una chiave principale salvata nel
  gestore di password del browser vengono mantenuti. L'interfaccia classica di
  zing non esiste più: i suoi indirizzi (`/tools`, `/console`) aprono la pagina di verifica (`/`).
- **Rapporti e sonde.** Rapporti, webhook e nomi dei file riportano `ekte` (ad es.
  `"tool": "ekte"`, `ekte-report.json`), così come le sonde inviate ai relay. Gli
  script che vi cercano `zing` vanno aggiornati.
- **Calendario.** L'intero livello di compatibilità (la lettura di `ZING_*`, la copia di `~/.zing`, il trasferimento di impostazioni del browser, cookie e chiave principale salvata, e gli indirizzi dell'interfaccia classica) è obsoleto e viene rimosso in ekte **1.0.0** (1.0.0rc1 è la prima versione senza di esso). Fino ad allora ogni parte continua a funzionare e il suo avviso indica questa versione; anche i vecchi indirizzi di pagina `/v2/…` rimandano fino alla 1.0.0. ekte non cancella mai un vecchio `~/.zing`, nemmeno quando la copia viene rimossa.
