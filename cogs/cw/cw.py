import discord
from discord.ext import commands
from discord import app_commands
import json
import os
from console_logger import logger
from bot_utils import OWNER_ID, owner_or_has_permissions, is_owner

BASE_DIR = os.path.dirname(__file__)
CONFIG_FILE = os.path.join(BASE_DIR, 'cw.json')

class CWCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config_file = CONFIG_FILE
        self.load_config()

    def load_config(self):
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
        elif os.path.exists('cw.json'):
            with open('cw.json', 'r', encoding='utf-8') as f:
                self.config = json.load(f)
            try:
                with open(self.config_file, 'w', encoding='utf-8') as f:
                    json.dump(self.config, f, indent=2, ensure_ascii=False)
            except Exception:
                pass
        else:
            self.config = {
                "embed_title": "CW - Clan War",
                "embed_description": "Clan War in corso!\n\n**Team Rossi:**\n{rossi_1}\n{rossi_2}\n{rossi_3}\n{rossi_4}\n\n**Team Verdi:**\n{verdi_1}\n{verdi_2}\n{verdi_3}\n{verdi_4}\n\n**Mappa:**\n{mappa_1}\n{mappa_2}\n{mappa_3}\n\n**Recap:**\n{recap_1}\n{recap_2}\n{recap_3}",
                "embed_color": 3447003,
                "footer": "Buona fortuna!"
            }

    @app_commands.command(name='reloadcw', description='Ricarica la configurazione di CW (solo admin)')
    @owner_or_has_permissions(administrator=True)
    async def reload_cw_cmd(self, interaction: discord.Interaction):
        try:
            self.load_config()
            await interaction.response.send_message('✅ Configurazione CW ricaricata con successo!', ephemeral=True)
            logger.info(f'Configurazione CW ricaricata da {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id}) in {interaction.guild.name}')
        except Exception as e:
            await interaction.response.send_message(f'❌ Errore nel ricaricare la configurazione CW: {e}', ephemeral=True)
            logger.error(f"Errore reloadcw da {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id}) in {interaction.guild.name}: {e}")

    @app_commands.command(name='cw', description='Crea un embed per la Clan War con numero, data, ora, team, mappa, recap e vincitore')
    @owner_or_has_permissions(administrator=True)
    @app_commands.describe(
        numero='Numero della Clan War',
        data='Data della Clan War',
        ora='Ora della Clan War',
        rossi='Giocatori team Rossi (separati da ;) - es: Giocatore1; Giocatore2; Giocatore3; Giocatore4',
        verdi='Giocatori team Verdi (separati da ;) - es: Giocatore1; Giocatore2; Giocatore3; Giocatore4',
        mappa='Mappe (separate da ;) - es: Mappa1; Mappa2; Mappa3',
        recap='Recap (separato da ;) - es: Info1; Info2; Info3',
        vincitore='Vincitore della Clan War (Rossi/Verde)'
    )
    async def cw_command(self, interaction: discord.Interaction, numero: str, data: str, ora: str, rossi: str, verdi: str, mappa: str, recap: str, vincitore: str = None):
        try:
            rossi_list = [player.strip() for player in rossi.split(';')]
            verdi_list = [player.strip() for player in verdi.split(';')]
            mappa_list = [map_item.strip() for map_item in mappa.split(';')]
            recap_list = [recap_item.strip() for recap_item in recap.split(';')]

            def format_players(player_list, team_name):
                formatted = []
                for i, player in enumerate(player_list):
                    if player:
                        if i >= 4:
                            formatted.append(f"> {player} (SUB)")
                        else:
                            formatted.append(f"> {player}")
                return '\n'.join(formatted) if formatted else f"> {team_name} 1\n> {team_name} 2\n> {team_name} 3\n> {team_name} 4"

            rossi_formatted = format_players(rossi_list, "Rossi")
            verdi_formatted = format_players(verdi_list, "Verde")

            mappa_list.extend([''] * (3 - len(mappa_list)))
            recap_list.extend([''] * (3 - len(recap_list)))

            description = self.config['embed_description']
            description = description.replace('{numerocw}', numero)
            description = description.replace('{data}', data)
            description = description.replace('{ora}', ora)
            description = description.replace('{rossi}', rossi_formatted)
            description = description.replace('{verdi}', verdi_formatted)
            for i in range(1, 3+1):
                description = description.replace(f'{'{'}mappa_{i}{'}'}', mappa_list[i-1] if mappa_list[i-1] else f'Mappa {i}')
                description = description.replace(f'{'{'}recap_{i}{'}'}', recap_list[i-1] if recap_list[i-1] else f'Recap {i}')
            description = description.replace('{vincitore}', vincitore if vincitore else 'TBD')

            embed = discord.Embed(
                title=self.config['embed_title'],
                description=description,
                color=self.config['embed_color']
            )

            if self.config.get('footer'):
                embed.set_footer(text=self.config['footer'])

            await interaction.response.send_message(embed=embed)
            logger.info(f'CW embed creato da {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id}) in {interaction.guild.name}')

        except Exception as e:
            await interaction.response.send_message(f"❌ Errore nella creazione dell'embed CW: {e}", ephemeral=True)
            logger.error(f"Errore comando /cw da {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id}) in {interaction.guild.name}: {e}")

async def setup(bot):
    await bot.add_cog(CWCog(bot))
