# Bot Discord Custom Warfare

Bot Discord per gestire partite custom con divisione automatica dei team.

## Funzionalità

- ✅ Monitora un canale vocale lobby specifico
- ✅ Quando 8 giocatori entrano, crea automaticamente:
  - Un canale di testo per annunciare i team
  - Due canali vocali: 🔴 ROSSO e 🟢 VERDE
  - Sposta automaticamente i primi 4 giocatori nel team ROSSO
  - Sposta automaticamente gli ultimi 4 giocatori nel team VERDE
- ✅ Pulizia automatica quando tutti i giocatori escono
- ✅ Comando `/cwend` per terminare manualmente la partita
- ✅ Comando `/cwstatus` per vedere lo stato della partita

## Installazione

1. **Installa Python 3.8 o superiore**

2. **Installa le dipendenze:**
```bash
pip install -r requirements.txt
```

3. **Configura il bot:**
   - Apri `config.json`
   - Inserisci il token del tuo bot Discord
   - Inserisci l'ID del canale vocale lobby
   - (Opzionale) Inserisci l'ID della categoria dove creare i canali

## Configurazione

### Ottenere il Token del Bot

1. Vai su [Discord Developer Portal](https://discord.com/developers/applications)
2. Crea una nuova applicazione o seleziona una esistente
3. Vai nella sezione "Bot"
4. Clicca su "Reset Token" e copia il token
5. Incollalo in `config.json` nel campo `token`

### Abilitare gli Intents

Nel Discord Developer Portal, nella sezione Bot:
- ✅ Abilita "Presence Intent"
- ✅ Abilita "Server Members Intent"
- ✅ Abilita "Message Content Intent"

### Invitare il Bot

Usa questo link (sostituisci CLIENT_ID con l'ID della tua applicazione):
```
https://discord.com/api/oauth2/authorize?client_id=CLIENT_ID&permissions=16796688&scope=bot%20applications.commands
```

Permessi necessari:
- Gestisci Canali
- Sposta Membri
- Invia Messaggi
- Gestisci Messaggi
- Connetti
- Parla

### Ottenere gli ID

Per ottenere gli ID dei canali:
1. Abilita la "Modalità Sviluppatore" in Discord (Impostazioni Utente > Avanzate)
2. Fai clic destro sul canale vocale lobby → Copia ID
3. Incolla l'ID in `config.json` nel campo `lobby_voice_channel_id`
4. (Opzionale) Fai lo stesso per una categoria se vuoi organizzare i canali

### Esempio config.json

```json
{
  "token": "MTIzNDU2Nzg5MDEyMzQ1Njc4OQ.GhIjKl.MnOpQrStUvWxYzAbCdEfGhIjKlMnOpQrStUv",
  "lobby_voice_channel_id": "1234567890123456789",
  "category_id": "9876543210987654321"
}
```

## Utilizzo

1. **Avvia il bot:**
```bash
python index.py
```

2. **Entra nel canale vocale lobby con almeno 8 giocatori**
   - Il bot creerà automaticamente i canali e dividerà i team

3. **Comandi disponibili:**
   - `/cwend` - Termina la partita e elimina tutti i canali
   - `/cwstatus` - Mostra lo stato della partita attiva

## Come Funziona

1. Il bot monitora il canale vocale lobby specificato
2. Quando 8 giocatori sono presenti:
   - Crea un canale di testo "🎮-partita-custom"
   - Crea due canali vocali: "🔴 ROSSO" e "🟢 VERDE"
   - I primi 4 giocatori entrati vengono assegnati al team ROSSO
   - Gli ultimi 4 giocatori entrati vengono assegnati al team VERDE
   - Tutti i giocatori vengono spostati nei rispettivi canali vocali
3. Quando tutti i giocatori escono dai canali, il bot elimina automaticamente i canali creati
4. Puoi usare `/cwend` per terminare manualmente la partita in qualsiasi momento

## Risoluzione Problemi

**Il bot non risponde:**
- Verifica che il token sia corretto
- Controlla che gli intents siano abilitati nel Developer Portal
- Assicurati che il bot abbia i permessi necessari nel server

**I giocatori non vengono spostati:**
- Verifica che il bot abbia il permesso "Sposta Membri"
- Assicurati che il ruolo del bot sia più alto dei ruoli dei giocatori

**I canali non vengono creati:**
- Verifica che il bot abbia il permesso "Gestisci Canali"
- Controlla che l'ID della categoria (se specificato) sia corretto

**I comandi slash non appaiono:**
- Aspetta qualche minuto dopo l'avvio del bot
- Prova a riavviare Discord
- Verifica che il bot abbia lo scope "applications.commands"

## Supporto

Per problemi o domande, controlla i log del bot nella console.
