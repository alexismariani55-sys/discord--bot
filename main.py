import re
import asyncio
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands

# =========================
# CONFIG
# =========================

TOKEN = "MTQ3OTkxMjE3MDcwNjgyOTQ0OQ.Gp7y15.F1YDWT8WEbinAPG6uKLTuZWmltEM6XgJla2nCM"

PREFIX = "!"

# IDs à remplacer
GOODBYE_CHANNEL_ID = 1422334058263744563  # salon où le bot envoie le message
WELCOME_CHANNEL_ID = 1422334054929399890  # salon où le bot envoie le message
FIRST_CHANNEL_ID = 123456789012345678     # salon où tu veux envoyer les nouveaux
AUTO_ROLE_ID = 1469902656859410576         # rôle auto à l'arrivée (0 si tu n'en veux pas)
STAFF_ROLE_ID = 1422333982024011856        # rôle staff à retirer en cas d'abus
STAFF_ROLE_ID = 1422333985106952222        # rôle staff à retirer en cas d'abus
STAFF_ROLE_ID = 1422333986436546622        # rôle staff à retirer en cas d'abus

STAFF_ROLE_ID = 1480424879902822401        # rôle staff à retirer en cas d'abus
STAFF_ROLE_ID = 1480424918435889212        # rôle staff à retirer en cas d'abus
STAFF_ROLE_ID = 1422333988965449758        # rôle staff à retirer en cas d'abus
STAFF_ROLE_ID = 1422333989905236118        # rôle staff à retirer en cas d'abus

# Anti-raid joins
JOIN_BURST_LIMIT = 20       # 20 joins...
JOIN_BURST_SECONDS = 20    # ...en 20 sec => alerte raid

# Anti-spam
SPAM_MSG_LIMIT = 5         # 5 messages...
SPAM_SECONDS = 4           # ...en 4 sec => timeout
TIMEOUT_MINUTES = 5

# Anti-invite
BLOCK_DISCORD_INVITES = True

# Derank auto si trop de bans
BAN_LIMIT = 5            # 5 bans
BAN_WINDOW_SECONDS = 600  # en 10 minutes

# =========================
# INTENTS
# =========================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True
intents.moderation = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# =========================
# STOCKAGE TEMPORAIRE
# =========================

recent_joins = deque()
user_message_cache = defaultdict(lambda: deque())
moderator_ban_cache = defaultdict(lambda: deque())

invite_regex = re.compile(r"(discord\.gg|discord\.com/invite)/", re.IGNORECASE)


def utcnow():
    return datetime.now(timezone.utc)


def cleanup_deque(dq: deque, seconds: int):
    now = utcnow()
    while dq and (now - dq[0]).total_seconds() > seconds:
        dq.popleft()


async def send_log(guild: discord.Guild, message: str):
    channel = guild.get_channel(LOG_CHANNEL_ID)
    if channel:
        await channel.send(message)


# =========================
# EVENTS
# =========================

@bot.event
async def on_ready():
    print(f"Bot connecté : {bot.user}")


@bot.event
async def on_member_join(member: discord.Member):
    guild = member.guild

    # auto rôle
    if AUTO_ROLE_ID:
        role = guild.get_role(AUTO_ROLE_ID)
        if role:
            try:
                await member.add_roles(role, reason="Auto-role arrivée")
            except discord.Forbidden:
                await send_log(guild, "❌ Impossible d'ajouter le rôle auto. Vérifie la hiérarchie des rôles.")

    # message de bienvenue
    welcome_channel = guild.get_channel(WELCOME_CHANNEL_ID)
    if welcome_channel:
        embed = discord.Embed(
            title="🎉 Bienvenue !",
            description=f"Bienvenue {member.mention} sur **{guild.name}**",
            color=discord.Color.green()
        )
        embed.add_field(name="Utilisateur", value=f"{member} (`{member.id}`)", inline=False)
        embed.add_field(name="Membres", value=str(guild.member_count), inline=True)
        embed.set_thumbnail(url=member.display_avatar.url)

        await welcome_channel.send(embed=embed)

    # détection join burst
    recent_joins.append(utcnow())
    cleanup_deque(recent_joins, JOIN_BURST_SECONDS)

    if len(recent_joins) >= JOIN_BURST_LIMIT:
        await send_log(
            guild,
            f"🚨 **Alerte anti-raid** : {len(recent_joins)} arrivées en moins de {JOIN_BURST_SECONDS} secondes."
        )


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    member = message.author

    # on laisse les admins tranquilles
    if member.guild_permissions.administrator:
        await bot.process_commands(message)
        return

    # anti invite discord
    if BLOCK_DISCORD_INVITES and invite_regex.search(message.content):
        try:
            await message.delete()
            await message.channel.send(
                f"{member.mention}, les invitations Discord ne sont pas autorisées ici.",
                delete_after=5
            )
            await send_log(message.guild, f"🔗 Invitation supprimée de {member.mention}.")
        except discord.Forbidden:
            pass
        return

    # anti spam simple
    dq = user_message_cache[member.id]
    dq.append(utcnow())
    cleanup_deque(dq, SPAM_SECONDS)

    if len(dq) >= SPAM_MSG_LIMIT:
        try:
            until = utcnow() + timedelta(minutes=TIMEOUT_MINUTES)
            await member.timeout(until, reason="Spam détecté")
            await message.channel.send(
                f"⏱️ {member.mention} a été mute {TIMEOUT_MINUTES} minutes pour spam.",
                delete_after=8
            )
            await send_log(message.guild, f"🛑 Timeout anti-spam appliqué à {member.mention}.")
            dq.clear()
        except discord.Forbidden:
            await send_log(message.guild, "❌ Impossible de timeout un membre. Vérifie les permissions du bot.")
        return

    await bot.process_commands(message)


@bot.event
async def on_member_ban(guild: discord.Guild, user: discord.User):
    await asyncio.sleep(1.5)

    try:
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
            if entry.target.id == user.id:
                moderator = entry.user

                if moderator.bot:
                    return

                dq = moderator_ban_cache[moderator.id]
                dq.append(utcnow())
                cleanup_deque(dq, BAN_WINDOW_SECONDS)

                if len(dq) >= BAN_LIMIT:
                    staff_member = guild.get_member(moderator.id)
                    staff_role = guild.get_role(STAFF_ROLE_ID)

                    if staff_member and staff_role and staff_role in staff_member.roles:
                        try:
                            await staff_member.remove_roles(
                                staff_role,
                                reason=f"Derank auto: {BAN_LIMIT} bans en moins de 10 minutes"
                            )
                            await send_log(
                                guild,
                                f"🚨 **Derank auto** : {staff_member.mention} a fait {BAN_LIMIT} bans en moins de 10 minutes. "
                                f"Le rôle **{staff_role.name}** a été retiré."
                            )
                            dq.clear()
                        except discord.Forbidden:
                            await send_log(
                                guild,
                                "❌ Impossible de retirer le rôle staff. Vérifie la hiérarchie des rôles."
                            )
                break
    except discord.Forbidden:
        await send_log(guild, "❌ Le bot n'a pas accès aux audit logs.")


# =========================
# COMMANDES UTILES
# =========================

@bot.command()
async def ping(ctx):
    await ctx.send(f"🏓 Pong : {round(bot.latency * 1000)} ms")


@bot.command()
@commands.has_permissions(administrator=True)
async def configtest(ctx):
    await ctx.send("✅ Le bot tourne bien.")


bot.run(TOKEN)
