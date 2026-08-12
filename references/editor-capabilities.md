# Capacità dell'editor locale

Leggere questa reference soltanto quando l'utente chiede come usare l'editor o quando occorre diagnosticare un controllo dell'interfaccia. Il percorso normale di revisione è descritto in [visual-review.md](visual-review.md).

L'editor consente di modificare copertina, titoli, corpi e chiusura; spostare o eliminare le sole slide interne; aggiungere commenti a una selezione, a una slide o all'intera sequenza; annullare l'ultima modifica locale; scegliere il sistema visivo e la modalità globale del logo.

Su una locuzione selezionata applica o rimuove grassetto, corsivo, sottolineatura ed evidenziatore adattivo. Le scorciatoie sono `Cmd/Ctrl+B`, `Cmd/Ctrl+I`, `Cmd/Ctrl+U` e `Cmd/Ctrl+Maiusc+H`. I controlli aggiornano i campi `*_bold`, `*_italic`, `*_underline` e `*_accent`, senza inserire Markdown. Una selezione parziale di una locuzione già formattata può rimuovere il trattamento completo.

Sono ammessi più trattamenti nello stesso testo quando riguardano unità distinte. L'approvazione è bloccata se la stessa unità usa più stili, due selezioni si sovrappongono, il corsivo reale non è disponibile o una locuzione è ambigua. La rimozione di tutti i grassetti non produce avvisi. Mostrare un solo messaggio per conflitto e nominare una sola volta la locuzione coinvolta.

Copertina e chiusura non sono eliminabili. La copertina non mostra cornice Editoriale, costellazione Geometrica o indice e guida Istituzionali. Nella copertina suggerire come commento `Aggiungi un disegno coerente col titolo`; nelle altre slide usare un esempio pertinente al contenuto.

Prima della conferma l'editor riepiloga quantità dei trattamenti tipografici, modalità del logo e disponibilità delle varianti chiare e scure. Mostra palette, sintesi dei caratteri e controlli operativi, ma non percorsi o metadati tecnici. Segnala il fallback tipografico soltanto quando un carattere non viene caricato.

La copertina finale appartiene al checkpoint visuale successivo: nella prima approvazione chiarire che potrà usare un'immagine generata, un'immagine fornita o una composizione tipografica.
