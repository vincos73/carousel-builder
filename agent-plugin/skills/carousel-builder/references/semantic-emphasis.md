# Enfasi semantica

Usare l'enfasi tipografica per creare ritmo senza compromettere la lettura. Il grassetto usa il carattere primario ed è disponibile in ogni profilo che possiede il peso necessario; il corsivo usa soltanto il secondo carattere approvato. Proporre massimo due enfasi per card e applicare nel renderer soltanto le scelte approvate.

## Sintassi

- `Il cambiamento è *già iniziato*` rende soltanto «già iniziato» nel secondo carattere approvato del profilo.
- Usare gli asterischi solo per il cambio di font, non per grassetto o corsivo Markdown.
- Racchiudere unità semantiche complete e usare massimo due segmenti per card.
- Dopo l’approvazione, registrare l’enfasi con il carattere primario in `cover_title_bold`, `title_bold` o `summary_bold`.
- Dopo l'approvazione, rimuovere gli asterischi e compilare `cover_title_serif`, `title_serif` o `summary_serif`.
- Ogni frase marcata `*_serif` usa il carattere `serif_italic` approvato. Se la famiglia è Playfair Display, usarla sempre in corsivo. Il sottotitolo opzionale di copertina usa lo stesso trattamento per intero e non richiede una marcatura semantica separata.

## Criteri

- Quando manca un secondo font approvato, usare soltanto `*_bold`; non simulare il corsivo con un font estraneo al profilo.
- Non introdurre automaticamente un secondo carattere in un profilo che prevede soltanto `display` e `body`.
- Nei testi narrativi preferire una sola locuzione breve in grassetto per slide. Il peso deve evidenziare il concetto decisivo, non la parola più lunga o frequente.
- Usare il secondo carattere per contrasto, svolta, voce espressiva o concetto memorabile.
- In modalità `narrative`, privilegiare una gerarchia ottenuta con peso, dimensione e spazio. L'enfasi con un secondo font resta facoltativa.
- Usare i campi `*_accent` per rilievo cromatico indipendente dal font.
- Non assegnare automaticamente accenti cromatici. Usarli soltanto quando richiesti o approvati nella prova visuale.
- Non affidare informazioni essenziali al solo cambio di font o colore: il testo deve conservare lo stesso significato anche senza enfasi visuale.
- Non scegliere parole in base a lunghezza, maiuscole o frequenza.
- Non spezzare nomi propri, denominazioni, modelli o locuzioni.
- Verificare che ogni frase indicata compaia esattamente nel testo.

Esempio:

```json
{
  "title": "La lezione è operativa",
  "title_bold": ["La lezione"],
  "title_serif": ["è operativa"],
  "title_accent": []
}
```
