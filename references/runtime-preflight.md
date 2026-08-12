# Preflight rapido della produzione

Prima dell'onboarding determinare, senza installare nulla, quali output sono realmente producibili nella sessione.

Verificare nell'ordine:

1. capacità di leggere integralmente la fonte;
2. runtime, librerie e percorsi bundled o già configurati dall'ambiente;
3. disponibilità di Python 3.10 o successivo, browser locale su `127.0.0.1` e ricezione degli eventi per il percorso `local-editor`;
4. disponibilità di un renderer con controllo affidabile di font, misure e ritorni a capo;
5. possibilità di generare o ricevere il visuale di copertina e di esportare PNG e PDF in percorsi accessibili all'utente.

Provare prima il runtime dichiarato dall'ambiente e soltanto dopo gli interpreti generici del sistema. Verificare gli import necessari e, quando utile, un rendering minimo in una cartella temporanea. Il fallimento di un candidato non è un limite da comunicare se un altro runtime disponibile supera il controllo.

Classificare il risultato:

- `renderer`: prova, PNG e PDF ripetibili con controllo tipografico;
- `adapter`: stessi artefatti tramite strumenti già disponibili che rispettano manifest e QA;
- `layout`: nessun controllo tipografico affidabile, quindi visuale di copertina quando possibile e layout dettagliato, senza presentarlo come rendering finale.

Non promettere formati non verificati e non installare dipendenze o browser. Comunicare il risultato previsto in una frase semplice, senza nomi tecnici, per esempio: «In questa sessione posso produrre le card PNG e il PDF finale».

Questo file serve solo a decidere rapidamente capacità e percorso. Prima della prova visuale e dell'export leggere e applicare [production-qa.md](production-qa.md), che resta il contratto completo e prevalente per dimensioni, prova a 480 px, proof, parità del renderer e controllo finale.
