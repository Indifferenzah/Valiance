import discord
from discord import ui
import json
import os
from console_logger import logger

class EmbedCreatorView(discord.ui.View):
    def __init__(self, embed, author_id):
        super().__init__(timeout=300)
        self.embed = embed
        self.author_id = author_id
        self.message_content = ""
        self.fields = []
        self.target_channel = None

    @discord.ui.select(
        placeholder="Seleziona cosa modificare",
        options=[
            discord.SelectOption(label="Titolo", value="title", description="Modifica il titolo dell'embed"),
            discord.SelectOption(label="Descrizione", value="description", description="Modifica la descrizione"),
            discord.SelectOption(label="Colore", value="color", description="Modifica il colore"),
            discord.SelectOption(label="Thumbnail", value="thumbnail", description="Modifica l'immagine thumbnail"),
            discord.SelectOption(label="Immagine", value="image", description="Modifica l'immagine principale"),
            discord.SelectOption(label="Footer", value="footer", description="Modifica il footer"),
            discord.SelectOption(label="Aggiungi Campo", value="add_field", description="Aggiungi un campo"),
            discord.SelectOption(label="Messaggio Fuori Embed", value="content", description="Modifica il messaggio fuori dall'embed"),
            discord.SelectOption(label="Scegli Canale", value="choose_channel", description="Scegli il canale dove inviare l'embed"),
            discord.SelectOption(label="Invia Embed", value="send", description="Invia l'embed nel canale selezionato"),
            discord.SelectOption(label="Annulla", value="cancel", description="Annulla la creazione")
        ]
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ Solo chi ha creato l'embed può modificarlo!", ephemeral=True)
            return

        choice = select.values[0]

        if choice == "send":
            await self.send_embed(interaction)
            return
        elif choice == "cancel":
            await interaction.response.edit_message(content="❌ Creazione embed annullata.", embed=None, view=None)
            return
        elif choice == "add_field":
            await self.add_field_modal(interaction)
            return
        elif choice == "choose_channel":
            await self.choose_channel_modal(interaction)
            return

        modal = EmbedModal(choice, self)
        await interaction.response.send_modal(modal)

    async def add_field_modal(self, interaction):
        modal = FieldModal(self)
        await interaction.response.send_modal(modal)

    async def choose_channel_modal(self, interaction):
        modal = ChannelModal(self)
        await interaction.response.send_modal(modal)

    async def send_embed(self, interaction):
        try:
            embed = self.embed.copy()
            for name, value, inline in self.fields:
                embed.add_field(name=name, value=value, inline=inline)

            target_channel = self.target_channel or interaction.channel
            await target_channel.send(content=self.message_content or None, embed=embed)
            await interaction.response.edit_message(content="✅ Embed inviato con successo!", embed=None, view=None)
            logger.info(f'Embed inviato da {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id}) in {interaction.guild.name}')
        except Exception as e:
            await interaction.response.send_message(f"❌ Errore nell'invio dell'embed: {e}", ephemeral=True)

class EmbedModal(discord.ui.Modal):
    def __init__(self, field_type, view):
        super().__init__(title=f"Modifica {field_type.capitalize()}")
        self.field_type = field_type
        self.view = view

        self.input = discord.ui.TextInput(
            label=f"Nuovo {field_type.capitalize()}",
            style=discord.TextStyle.paragraph,
            placeholder=self.get_placeholder(field_type),
            required=True,
            max_length=4000
        )
        self.add_item(self.input)

    def get_placeholder(self, field_type):
        placeholders = {
            "title": "Inserisci il titolo dell'embed",
            "description": "Inserisci la descrizione",
            "color": "Inserisci un colore (es: #ff0000 o 16711680)",
            "thumbnail": "Inserisci l'URL dell'immagine thumbnail",
            "image": "Inserisci l'URL dell'immagine principale",
            "footer": "Inserisci il testo del footer",
            "content": "Inserisci il messaggio fuori dall'embed"
        }
        return placeholders.get(field_type, "Inserisci il valore")

    async def on_submit(self, interaction: discord.Interaction):
        value = self.input.value.strip()

        try:
            if self.field_type == "color":
                if value.startswith("#"):
                    value = int(value[1:], 16)
                else:
                    value = int(value)
                self.view.embed.color = value
            elif self.field_type == "thumbnail":
                self.view.embed.set_thumbnail(url=value)
            elif self.field_type == "image":
                self.view.embed.set_image(url=value)
            elif self.field_type == "footer":
                self.view.embed.set_footer(text=value)
            elif self.field_type == "content":
                self.view.message_content = value
            else:
                setattr(self.view.embed, self.field_type, value)

            await interaction.response.edit_message(embed=self.view.embed, view=self.view)
        except Exception as e:
            await interaction.response.send_message(f"❌ Errore nella modifica: {e}", ephemeral=True)

class FieldModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="Aggiungi Campo")
        self.view = view

        self.name_input = discord.ui.TextInput(
            label="Nome del Campo",
            placeholder="Inserisci il nome del campo",
            required=True,
            max_length=256
        )
        self.value_input = discord.ui.TextInput(
            label="Valore del Campo",
            style=discord.TextStyle.paragraph,
            placeholder="Inserisci il valore del campo",
            required=True,
            max_length=1024
        )
        self.inline_input = discord.ui.TextInput(
            label="Inline (true/false)",
            placeholder="true o false (default: false)",
            required=False,
            max_length=5
        )

        self.add_item(self.name_input)
        self.add_item(self.value_input)
        self.add_item(self.inline_input)

    async def on_submit(self, interaction: discord.Interaction):
        name = self.name_input.value.strip()
        value = self.value_input.value.strip()
        inline = self.inline_input.value.strip().lower() == "true"

        if len(self.view.fields) >= 25:
            await interaction.response.send_message("❌ Puoi aggiungere massimo 25 campi!", ephemeral=True)
            return

        self.view.fields.append((name, value, inline))

        embed = self.view.embed.copy()
        for n, v, i in self.view.fields:
            embed.add_field(name=n, value=v, inline=i)

        await interaction.response.edit_message(embed=embed, view=self.view)

class ChannelModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="Scegli Canale")
        self.view = view

        self.channel_input = discord.ui.TextInput(
            label="ID del Canale",
            placeholder="Inserisci l'ID del canale dove inviare l'embed",
            required=True,
            max_length=20
        )
        self.add_item(self.channel_input)

    async def on_submit(self, interaction: discord.Interaction):
        channel_id = self.channel_input.value.strip()
        try:
            channel = interaction.guild.get_channel(int(channel_id))
            if not channel:
                await interaction.response.send_message("❌ Canale non trovato!", ephemeral=True)
                return
            self.view.target_channel = channel
            await interaction.response.send_message(f"✅ Canale impostato a {channel.mention}!", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ ID canale non valido!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Errore: {e}", ephemeral=True)
