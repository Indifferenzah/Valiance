import discord
from discord.ext import commands
from discord import app_commands
import json
import os
from console_logger import logger
from bot_utils import OWNER_ID, owner_or_has_permissions, is_owner

class RulesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config_file = 'regole.json'
        self.reload_config()

    def reload_config(self):
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.rules_config = json.load(f)
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
            await interaction.response.send_message(
                "❌ Errore: canale regole non configurato in regole.json.",
                ephemeral=True
            )
            return

        rules_channel = interaction.guild.get_channel(int(rules_channel_id))
        if not rules_channel:
            await interaction.response.send_message(
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

        image_files = [f for f in os.listdir('.') if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp'))]
        file = None
        if image_files:
            image_file = image_files[0]
            file = discord.File(image_file)

        if file:
            await rules_channel.send(embed=embed, file=file)
        else:
            await rules_channel.send(embed=embed)
        await interaction.response.send_message(f"✅ Regole inviate con successo in {rules_channel.mention}!", ephemeral=True)

async def setup(bot):
    await bot.add_cog(RulesCog(bot))
