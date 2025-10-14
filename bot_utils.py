import discord
from discord import app_commands

OWNER_ID = 1123622103917285418

def is_owner(user_or_id):
    try:
        if isinstance(user_or_id, int):
            return user_or_id == OWNER_ID
        return getattr(user_or_id, 'id', None) == OWNER_ID
    except Exception:
        return False

def owner_or_has_permissions(**perms):
    def _predicate(interaction: discord.Interaction):
        try:
            if is_owner(interaction.user):
                return True
            user_perms = interaction.user.guild_permissions
            for perm_name, required in perms.items():
                if getattr(user_perms, perm_name, False) != required:
                    return False
            return True
        except Exception:
            return False

    return app_commands.check(_predicate)
