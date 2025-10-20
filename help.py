import discord
from discord import app_commands
from discord.ext import commands

from console_logger import logger

categories = {
    'moderation': {
        'emoji': '🛡️',
        'name': 'Moderazione',
        'commands': [
            '`/ban` - Banna un membro',
            '`/kick` - Kicka un membro',
            '`/mute` - Muta un membro',
            '`/unmute` - Smuta un membro',
            '`/warn` - Aggiungi un warn',
            '`/unwarn` - Rimuovi un warn',
            '`/listwarns` - Mostra i warn',
            '`/clearwarns` - Rimuovi tutti i warn',
            '`/listban` - Mostra i ban',
            '`/checkban` - Controlla se un utente è bannato',
            '`/checkmute` - Controlla se un utente è mutato',
            '`/nick` - Imposta nickname a un utente'
        ]
    },
    'ticket': {
        'emoji': '🎫',
        'name': 'Ticket',
        'commands': [
            '`/ticketpanel` - Crea pannello ticket',
            '`/close` - Chiudi ticket',
            '`/transcript` - Genera transcript',
            '`/add` - Aggiungi utente al ticket',
            '`/remove` - Rimuovi utente dal ticket',
            '`/rename` - Rinomina ticket',
            '`/blacklist` - Blacklist utente'
        ]
    },
    'utility': {
        'emoji': '🔧',
        'name': 'Utilità',
        'commands': [
            '`/ping` - Mostra latenza bot',
            '`/uptime` - Mostra uptime bot',
            '`/purge` - Elimina messaggi',
            '`/delete` - Elimina canale',
            '`/cwend` - Termina partita CW',
            '`/ruleset` - Mostra ruleset',
            '`/setruleset` - Imposta ruleset',
            '`/startct` - Avvia counter',
            '`/stopct` - Ferma counter',
            '`/embed` - Crea embed personalizzato',
            '`/regole` - Manda le regole del server'
        ]
    },
    'autorole': {
        'emoji': '🎭',
        'name': 'AutoRole',
        'commands': [
            '`/createreact` - Crea messaggio reazione ruoli'
        ]
    },
    'fun': {
        'emoji': '🎲',
        'name': 'Fun',
        'commands': [
            '`/coinflip` - Lancia una moneta',
            '`/roll` - Tira un dado',
            '`/avatar` - Mostra l\'avatar di un utente',
            '`/userinfo` - Mostra informazioni su un utente',
            '`/serverinfo` - Mostra informazioni sul server'
        ]
    },
    'tts': {
        'emoji': '📝',
        'name': 'TTS',
        'commands': [
            '`/say` - Usa TTS',
            '`/voice` - Imposta voce',
            '`/volume` - Cambia volume',
            '`/stop` - Ferma TTS'
        ]
    },
    'logs': {
        'emoji': '⚙️',
        'name': 'Logs',
        'commands': [
            '`/logs` - Visualizza file di log',
            '`/dellogs` - Elimina file di log',
            '`/setlogchannel` - Imposta canali di log'
        ]
    },
    'reload': {
        'emoji': '🔄',
        'name': 'Reload',
        'commands': [
            '`/reloadlog` - Ricarica config di log',
            '`/reloadticket` - Ricarica config di ticket',
            '`/reloadmod` - Ricarica config di moderazione',
            '`/reloadconfig` - Ricarica config generale',
            '`/reloadall` - Ricarica tutte le configurazioni'
        ]
    }
}

class HelpSelectView(discord.ui.View):
    def __init__(self, author_id, bot):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.bot = bot

        options = [discord.SelectOption(label='Tutti', value='all', emoji='📋')]
        for key, cat in categories.items():
            options.append(discord.SelectOption(label=cat['name'], value=key, emoji=cat['emoji']))

        self.select = discord.ui.Select(placeholder='Seleziona una categoria...', options=options)
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message('❌ Solo chi ha eseguito il comando può usare questo menu!', ephemeral=True)
            return

        selected = self.select.values[0]

        embed = discord.Embed(
            title='📋 Comandi Disponibili',
            color=0x00ff00
        )

        if selected == 'all':
            embed.description = 'Ecco una lista di tutti i comandi slash disponibili su questo bot:'
            for key, cat in categories.items():
                embed.add_field(
                    name=f"{cat['emoji']} {cat['name']}",
                    value='\n'.join(cat['commands']),
                    inline=False
                )
        else:
            cat = categories[selected]
            embed.title = f"{cat['emoji']} {cat['name']}"
            embed.description = f"Comandi disponibili nella categoria **{cat['name']}**:"
            embed.add_field(
                name='Comandi',
                value='\n'.join(cat['commands']),
                inline=False
            )

        embed.set_footer(text='Valiance Bot | Usa / per accedere ai comandi')

        await interaction.response.edit_message(embed=embed, view=self)

class HelpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='help', description='Mostra una lista di tutti i comandi slash disponibili')
    async def slash_help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title='📋 Comandi Disponibili',
            description='**Help** | **Valiance**\n\nSeleziona una categoria dal menu sottostante per vedere i comandi disponibili:\n⚙️ | Developer: `indifferenzah`\n🔗 | Discord: https://discord.gg/NACE9V7kfx',
            color=0x00ff00
        )

        embed.set_footer(text='Valiance Bot | Usa / per accedere ai comandi')

        view = HelpSelectView(interaction.user.id, self.bot)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        logger.info(f'Utente {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id}) ha usato il comando /help')

async def setup(bot):
    await bot.add_cog(HelpCog(bot))
