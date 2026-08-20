# Enfasi semantica

Usare l'enfasi tipografica per creare ritmo senza compromettere la lettura. Nelle card interne il grassetto con il carattere principale è la proposta predefinita, non un requisito: l'utente può rimuoverlo senza avvisi e senza bloccare l'approvazione. Il corsivo è un accento facoltativo: può usare la vera variante italic del carattere principale oppure un carattere corsivo secondario, secondo il profilo approvato. Applicare nel renderer soltanto le scelte approvate.

## Ruoli

- `*_bold`: concetto decisivo, reso con un peso più forte del carattere principale del campo.
- `*_italic`: sfumatura, svolta, voce espressiva, citazione breve o concetto memorabile, reso con il ruolo corsivo risolto dal profilo.
- `*_underline`: enfasi lineare discreta, resa nel colore del testo per restare leggibile su fondi chiari e scuri.
- `*_accent`: evidenziatore cromatico adattivo del brand. Usare l'accento dichiarato quando mantiene contrasto sufficiente con il testo; altrimenti derivarne una variante più scura con testo chiaro o più chiara con testo scuro.
- `*_serif`: alias legacy di `*_italic`; accettarlo nei manifest precedenti, ma usare `*_italic` nei nuovi manifest.

Non confondere corsivo e secondo carattere. Il corsivo può appartenere alla stessa famiglia del testo principale. Non inclinare artificialmente un font privo di una vera variante italic.

## Risoluzione del corsivo

Risolvere una sola modalità corsiva coerente per l'intero carosello, nell'ordine:

1. `brand.fonts.emphasis_italic`, quando fornito o approvato esplicitamente;
2. `brand.fonts.body_italic`, quando rappresenta la vera variante corsiva della famiglia principale;
3. `brand.fonts.serif_italic`, come ruolo legacy o secondo carattere corsivo approvato;
4. il corsivo del profilo neutro, soltanto dopo scelta esplicita del tema neutro.

Se nessun file o font corsivo reale è disponibile, non sintetizzarlo: disabilitare il comando per nuove selezioni. Se un manifest esistente contiene già `*_italic`, mostrare il fallback diritto e un avviso consultivo senza bloccare `Genera`. Mostrare sempre nell'interfaccia la famiglia effettiva, per esempio `Corsivo · Barlow Italic`, `Corsivo · Playfair Display Italic` oppure `fallback diritto`.

## Editor locale

Quando l'utente seleziona una locuzione, offrire i comandi `Grassetto`, `Corsivo`, `Sottolinea`, `Evidenzia` e `Commenta` senza inserire Markdown nel testo. I comandi aggiornano direttamente i campi espliciti del manifest e l'anteprima.

- Consentire il toggle e la rimozione delle enfasi.
- Dopo l'approvazione dei testi, trattare una modifica alle sole enfasi come variazione visuale: conservare la ricevuta editoriale, invalidare la prova corrente e richiedere soltanto una nuova prova visuale. Non marcare alt text o trascrizione come stale quando copy e ordine restano identici.
- Mostrare le enfasi direttamente nell'anteprima in tempo reale. Non duplicarle con chip, pill o altri elementi esterni al testo.
- Supportare `Cmd/Ctrl+B`, `Cmd/Ctrl+I`, `Cmd/Ctrl+U` e `Cmd/Ctrl+Maiusc+H` quando una selezione testuale è attiva.
- Usare `aria-pressed`, nomi accessibili completi e focus visibile.
- Non accettare una selezione vuota, ambigua perché ripetuta nel testo o sovrapposta a un'altra enfasi.
- Non mostrare avvisi quando l'utente rimuove tutti i grassetti. Consentire stati transitori durante `Invia correzioni`, mostrando un avviso inline soltanto per enfasi ambigue, sovrapposte, non supportate o eccessive; bloccare `Approva profilo e testi` finché questi problemi non sono risolti.

## Criteri

- Nelle card narrative interne proporre di default una `summary_bold` con una locuzione breve e completa. Il peso deve evidenziare il concetto decisivo, non la parola più lunga o frequente.
- Nelle card sezionali che contengono un corpo applicare la stessa proposta iniziale. Se la card contiene soltanto un titolo, la gerarchia del titolo è sufficiente.
- Consentire all'utente di rimuovere ogni `*_bold`: l'assenza di grassetti è uno stato valido e non genera avvisi.
- Consentire più trattamenti nella stessa card quando riguardano parole o locuzioni distinte. Il corsivo richiede sempre una vera variante risolta dal profilo.
- Copertina e chiusura possono usare una gerarchia più espressiva conforme al profilo.
- Non applicare più di uno tra `*_bold`, `*_italic`, `*_underline` e `*_accent` alla stessa parola o locuzione e non sovrapporre le selezioni.
- Non affidare informazioni essenziali al solo cambio di peso, stile, font o colore.
- Non scegliere parole in base a lunghezza, maiuscole o frequenza.
- Non spezzare nomi propri, denominazioni, modelli o locuzioni.
- Verificare che ogni locuzione compaia una sola volta e in modo esatto nel testo associato. Se ricorre più volte, richiedere una selezione più lunga e univoca.

Esempio:

```json
{
  "summary": "La lezione è operativa.\nIl cambiamento è già iniziato.",
  "summary_bold": ["La lezione è operativa"],
  "summary_italic": ["già iniziato"],
  "summary_underline": [],
  "summary_accent": []
}
```

## Evidenziatore adattivo

Calcolare il colore dell'evidenziatore per ogni slide, dopo aver risolto fondo e colore del testo:

1. usare `brand.palette.accent` se raggiunge almeno 4.5:1 rispetto al testo corrente;
2. se non basta, derivare dall'accento la variante più vicina che raggiunge il contrasto, scurendola quando il testo è chiaro e schiarendola quando il testo è scuro;
3. mantenere il colore del testo invariato e verificare che l'evidenziatore resti distinguibile dal fondo;
4. ripetere il calcolo separatamente sulle slide chiare, scure e sulle copertine con immagine.

Non scegliere un unico colore globale quando il carosello alterna i fondi.
