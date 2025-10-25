import discord
from discord.ext import commands
from discord import app_commands
import json
import os
from console_logger import logger
from bot_utils import OWNER_ID, owner_or_has_permissions, is_owner

BASE_DIR = os.path.dirname(__file__)
RULES_JSON = os.path.join(BASE_DIR, 'regole.json')

class RulesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config_file = RULES_JSON
        self.reload_config()

    @app_commands.command(name='reloadregole', description='Ricarica la configurazione delle regole (solo admin)')
    @owner_or_has_permissions(administrator=True)
    async def reload_regole(self, interaction: discord.Interaction):
        try:
            self.reload_config()
            await interaction.response.send_message('✅ Configurazione regole ricaricata con successo!', ephemeral=True)
            logger.info(f'Configurazione regole ricaricata da {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id}) in {interaction.guild.name}')
        except Exception as e:
            await interaction.response.send_message(f"❌ Errore nel ricaricare la configurazione regole: {e}", ephemeral=True)
            logger.error(f"Errore reloadregole da {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id}) in {interaction.guild.name}: {e}")

    def reload_config(self):
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.rules_config = json.load(f)
        elif os.path.exists('regole.json'):
            with open('regole.json', 'r', encoding='utf-8') as f:
                self.rules_config = json.load(f)
            try:
                with open(self.config_file, 'w', encoding='utf-8') as f:
                    json.dump(self.rules_config, f, indent=2, ensure_ascii=False)
            except Exception:
                pass
        else:
            self.rules_config = {
                "channel_id": None,
                "embed": {
                    "title": "Regolamento",
                    "description": "Leggi attentamente le regole!",
                    "color": 5763719,
                    "thumbnail": None,
                    "footer": "Valiance | Regolamento",
                    "fields": []
                }
            }

    @app_commands.command(name="regole", description="Invia l'embed con le regole nel canale configurato")
    @owner_or_has_permissions(administrator=True)
    async def regole(self, interaction: discord.Interaction):
        await interaction.response.send_message("✅ Configurazione regole ricaricata con successo!", ephemeral=True)
        rules_channel_id = self.rules_config.get("channel_id")
        if not rules_channel_id:
            await interaction.followup.send(
                "❌ Errore: canale regole non configurato in regole.json.",
                ephemeral=True
            )
            return

        rules_channel = interaction.guild.get_channel(int(rules_channel_id))
        if not rules_channel:
            await interaction.followup.send(
                "❌ Errore: canale regole non trovato o ID non valido in regole.json.",
                ephemeral=True
            )
            return

        embed_data = self.rules_config.get("embed", {})
        embed = discord.Embed(
            title=embed_data.get("title", "Regolamento"),
            description=embed_data.get("description", ""),
            color=embed_data.get("color", 5763719)
        )

        thumbnail = embed_data.get("thumbnail")
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)

        footer = embed_data.get("footer")
        footer_icon = embed_data.get("footer_icon")
        if footer_icon == "server":
            embed.set_footer(text=footer, icon_url=interaction.guild.icon.url if interaction.guild.icon else None)
        elif footer:
            embed.set_footer(text=footer)

        fields = embed_data.get("fields", [])
        for field in fields:
            embed.add_field(
                name=field.get("name", ""),
                value=field.get("value", ""),
                inline=field.get("inline", False)
            )

        # Attach first image file found in this cog's directory
        image_path = None
        for fname in os.listdir(BASE_DIR):
            if fname.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
                image_path = os.path.join(BASE_DIR, fname)
                break
        file = discord.File(image_path) if image_path and os.path.exists(image_path) else None

        if file:
            await rules_channel.send(embed=embed, file=file)
        else:
            await rules_channel.send(embed=embed)
        await interaction.followup.send(f"✅ Regole inviate con successo in {rules_channel.mention}!", ephemeral=True)

async def setup(bot):
    await bot.add_cog(RulesCog(bot))
