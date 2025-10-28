import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import random
import time
import io
from typing import Optional, Tuple
from PIL import Image, ImageDraw, ImageFont

from bot_utils import owner_or_has_permissions
from json_store import load_json, save_json

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')
DATA_PATH = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')), 'data', 'levels.json')


def load_config():
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {
            "enabled": True,
            "text_xp": {"min": 5, "max": 15, "cooldown_seconds": 60, "excluded_channel_ids": [], "excluded_role_ids": [], "multiplier_roles": {}},
            "voice_xp": {"enabled": True, "per_min_min": 2, "per_min_max": 5, "exclude_muted": True, "exclude_deaf": True, "exclude_afk_channel_ids": [], "excluded_role_ids": [], "multiplier_roles": {}},
            "leaderboard": {"page_size": 10},
            "rank_card": {"width": 934, "height": 282, "background": "assets/rankcard/rank_black.png", "bar_color": "#14ff72", "bar_bg": "#1f1f1f", "text_color": "#ffffff", "font_path": "assets/rankcard/Roboto-Bold.ttf"}
        }


def user_has_excluded_role(member: discord.Member, role_ids):
    return any(str(r.id) in set(map(str, role_ids)) for r in member.roles)


def get_multiplier(member: discord.Member, mapping: dict) -> float:
    mult = 1.0
    for rid, factor in mapping.items():
        try:
            if any(str(r.id) == str(rid) for r in member.roles):
                mult = max(mult, float(factor))
        except Exception:
            continue
    return mult


def level_from_xp(total_xp: int) -> Tuple[int, int, int]:
    # Simple curve: next = 5*lvl^2 + 50*lvl + 100
    level = 0
    xp = total_xp
    while True:
        needed = 5 * level * level + 50 * level + 100
        if xp < needed:
            return level, xp, needed
        xp -= needed
        level += 1


class LevelsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config = load_config()
        self.voice_loop.start()

    def cog_unload(self):
        try:
            self.voice_loop.cancel()
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_ready(self):
        # No DB init needed with JSON storage
        pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if not self.config.get('enabled', True):
            return
        text_cfg = self.config.get('text_xp', {})
        if str(message.channel.id) in set(map(str, text_cfg.get('excluded_channel_ids', []))):
            return
        if isinstance(message.author, discord.Member) and user_has_excluded_role(message.author, text_cfg.get('excluded_role_ids', [])):
            return

        now = int(time.time())
        cooldown = int(text_cfg.get('cooldown_seconds', 60))
        data = await load_json(DATA_PATH, {})
        gid = str(message.guild.id)
        uid = str(message.author.id)
        g = data.get(gid, {})
        users = g.get('users', {})
        u = users.get(uid, {"text_xp": 0, "voice_xp": 0, "last_msg_xp_at": 0})
        last = int(u.get('last_msg_xp_at', 0) or 0)
        if last and now - last < cooldown:
            return

        amount = random.randint(int(text_cfg.get('min', 5)), int(text_cfg.get('max', 15)))
        mult = get_multiplier(message.author, text_cfg.get('multiplier_roles', {}))
        amount = int(amount * mult)

        u['text_xp'] = int(u.get('text_xp', 0)) + amount
        u['last_msg_xp_at'] = now
        users[uid] = u
        g['users'] = users
        data[gid] = g
        await save_json(DATA_PATH, data)

    @tasks.loop(minutes=1)
    async def voice_loop(self):
        await self.bot.wait_until_ready()
        # Simple per-minute scan across voice channels for connected members
        try:
            if not self.config.get('voice_xp', {}).get('enabled', True):
                return
            vcfg = self.config.get('voice_xp', {})
            per_min = random.randint(int(vcfg.get('per_min_min', 2)), int(vcfg.get('per_min_max', 5)))
            for guild in self.bot.guilds:
                for vc in guild.voice_channels:
                    if str(vc.id) in set(map(str, vcfg.get('exclude_afk_channel_ids', []))):
                        continue
                    members = [m for m in vc.members if not m.bot]
                    for m in members:
                        if isinstance(m, discord.Member):
                            if vcfg.get('exclude_muted', True) and (m.voice.self_mute or m.voice.mute):
                                continue
                            if vcfg.get('exclude_deaf', True) and (m.voice.self_deaf or m.voice.deaf):
                                continue
                            if user_has_excluded_role(m, vcfg.get('excluded_role_ids', [])):
                                continue
                            mult = get_multiplier(m, vcfg.get('multiplier_roles', {}))
                            amount = int(per_min * mult)
                            data = await load_json(DATA_PATH, {})
                            gid = str(guild.id)
                            uid = str(m.id)
                            g = data.get(gid, {})
                            users = g.get('users', {})
                            u = users.get(uid, {"text_xp": 0, "voice_xp": 0, "last_msg_xp_at": 0})
                            u['voice_xp'] = int(u.get('voice_xp', 0)) + amount
                            users[uid] = u
                            g['users'] = users
                            data[gid] = g
                            await save_json(DATA_PATH, data)
        except Exception:
            pass

    @voice_loop.before_loop
    async def before_voice_loop(self):
        await self.bot.wait_until_ready()

    async def generate_rank_card(self, member: discord.Member, mode: str = 'text') -> Optional[discord.File]:
        cfg = self.config.get('rank_card', {})
        width = int(cfg.get('width', 934))
        height = int(cfg.get('height', 282))
        bg_path = cfg.get('background')
        bar_color = cfg.get('bar_color', '#14ff72')
        bar_bg = cfg.get('bar_bg', '#1f1f1f')
        text_color = cfg.get('text_color', '#ffffff')
        font_path = cfg.get('font_path')
        try:
            bg = Image.open(bg_path).convert('RGBA') if bg_path and os.path.exists(bg_path) else Image.new('RGBA', (width, height), (0, 0, 0, 255))
            if bg.size != (width, height):
                bg = bg.resize((width, height))
            draw = ImageDraw.Draw(bg)
            try:
                font_large = ImageFont.truetype(font_path, 42) if font_path and os.path.exists(font_path) else ImageFont.load_default()
                font_small = ImageFont.truetype(font_path, 24) if font_path and os.path.exists(font_path) else ImageFont.load_default()
            except Exception:
                font_large = ImageFont.load_default()
                font_small = ImageFont.load_default()

            # Fetch XP from JSON
            data = await load_json(DATA_PATH, {})
            gid = str(member.guild.id)
            uid = str(member.id)
            users = data.get(gid, {}).get('users', {})
            u = users.get(uid, {"text_xp": 0, "voice_xp": 0})
            text_xp = int(u.get('text_xp', 0))
            voice_xp = int(u.get('voice_xp', 0))
            xp = text_xp if mode == 'text' else voice_xp
            level, cur_xp, needed = level_from_xp(xp)

            # Avatar circle
            try:
                avatar_asset = member.display_avatar.replace(size=256)
                avatar_bytes = await avatar_asset.read()
                avatar = Image.open(io.BytesIO(avatar_bytes)).convert('RGBA')
            except Exception:
                avatar = Image.new('RGBA', (256, 256), (40, 40, 40, 255))
            avatar = avatar.resize((220, 220))
            mask = Image.new('L', (220, 220), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse((0, 0, 220, 220), fill=255)
            bg.paste(avatar, (30, 31), mask)

            # Text right side
            username = f"{member.display_name}"
            draw.text((270, 40), username, font=font_large, fill=text_color)
            mode_text = 'Text' if mode == 'text' else 'Voice'
            draw.text((270, 95), f"Livello {level} • {mode_text}", font=font_small, fill=text_color)

            # Progress bar
            bar_x, bar_y, bar_w, bar_h = 270, 150, 620, 30
            draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], radius=15, fill=bar_bg)
            if needed > 0:
                progress = max(0.0, min(1.0, cur_xp / needed))
            else:
                progress = 1.0
            fill_w = int(bar_w * progress)
            if fill_w > 0:
                draw.rounded_rectangle([bar_x, bar_y, bar_x + fill_w, bar_y + bar_h], radius=15, fill=bar_color)
            draw.text((270, 190), f"XP: {xp} • Mancano {needed - cur_xp} XP", font=font_small, fill=text_color)

            # Save to bytes
            import io
            buf = io.BytesIO()
            bg.save(buf, format='PNG')
            buf.seek(0)
            return discord.File(buf, filename='rank.png')
        except Exception:
            return None

    @app_commands.command(name='rank', description='Mostra la tua rank card (text/voice)')
    @app_commands.describe(user='Utente da mostrare', mode='text o voice')
    async def slash_rank(self, interaction: discord.Interaction, user: Optional[discord.Member] = None, mode: Optional[str] = 'text'):
        member = user or interaction.user
        mode = (mode or 'text').lower()
        if mode not in ('text', 'voice'):
            mode = 'text'
        file = await self.generate_rank_card(member, mode)
        if file is None:
            await interaction.response.send_message('Impossibile generare la rank card ora.', ephemeral=True)
            return
        await interaction.response.send_message(file=file, ephemeral=False)

    @app_commands.command(name='leaderboard', description='Mostra la classifica XP')
    @app_commands.describe(mode='text o voice', page='Pagina (da 1)')
    async def slash_leaderboard(self, interaction: discord.Interaction, mode: Optional[str] = 'text', page: Optional[int] = 1):
        await interaction.response.defer()
        mode = (mode or 'text').lower()
        page = max(1, int(page or 1))
        page_size = int(self.config.get('leaderboard', {}).get('page_size', 10))
        offset = (page - 1) * page_size
        data = await load_json(DATA_PATH, {})
        gid = str(interaction.guild.id)
        users = data.get(gid, {}).get('users', {})
        items = []
        for uid, u in users.items():
            xp = int(u.get('text_xp', 0)) if mode == 'text' else int(u.get('voice_xp', 0))
            items.append((int(uid), xp))
        items.sort(key=lambda x: x[1], reverse=True)
        slice_items = items[offset:offset + page_size]
        if not slice_items:
            await interaction.followup.send('Nessun dato in classifica.')
            return
        desc = []
        rank_start = offset + 1
        for i, (uid, xp) in enumerate(slice_items, start=rank_start):
            user = interaction.guild.get_member(uid) or await interaction.guild.fetch_member(uid)
            desc.append(f"**#{i}** {user.mention if user else uid} — {xp} XP")
        embed = discord.Embed(title=f"Classifica {mode.capitalize()}", description='\n'.join(desc), color=0x14ff72)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name='givexp', description='Dai XP a un utente (solo admin)')
    @owner_or_has_permissions(administrator=True)
    @app_commands.describe(user='Utente', amount='Quantità', mode='text o voice')
    async def slash_givexp(self, interaction: discord.Interaction, user: discord.Member, amount: int, mode: Optional[str] = 'text'):
        col = 'text_xp' if (mode or 'text').lower() == 'text' else 'voice_xp'
        data = await load_json(DATA_PATH, {})
        gid = str(interaction.guild.id)
        uid = str(user.id)
        g = data.get(gid, {})
        users = g.get('users', {})
        u = users.get(uid, {"text_xp": 0, "voice_xp": 0, "last_msg_xp_at": 0})
        u[col] = int(u.get(col, 0)) + int(amount)
        users[uid] = u
        g['users'] = users
        data[gid] = g
        await save_json(DATA_PATH, data)
        await interaction.response.send_message(f'Aggiunti {amount} XP {"testo" if col=="text_xp" else "voice"} a {user.mention}.', ephemeral=True)

    @app_commands.command(name='setxp', description='Setta gli XP di un utente (solo admin)')
    @owner_or_has_permissions(administrator=True)
    @app_commands.describe(user='Utente', amount='Quantità', mode='text o voice')
    async def slash_setxp(self, interaction: discord.Interaction, user: discord.Member, amount: int, mode: Optional[str] = 'text'):
        col = 'text_xp' if (mode or 'text').lower() == 'text' else 'voice_xp'
        data = await load_json(DATA_PATH, {})
        gid = str(interaction.guild.id)
        uid = str(user.id)
        g = data.get(gid, {})
        users = g.get('users', {})
        u = users.get(uid, {"text_xp": 0, "voice_xp": 0, "last_msg_xp_at": 0})
        u[col] = int(amount)
        users[uid] = u
        g['users'] = users
        data[gid] = g
        await save_json(DATA_PATH, data)
        await interaction.response.send_message(f'Settati {amount} XP {"testo" if col=="text_xp" else "voice"} per {user.mention}.', ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(LevelsCog(bot))
