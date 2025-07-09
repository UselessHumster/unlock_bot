from aiogram import Bot

domain = 'alkaloid.com.mk'
search_zone = 'OU=Rusija,OU=Branch Offices,DC=AlkaloidAD,DC=local'

fake_locked_users = b'\r\n\r\nAccountExpirationDate : \r\nDistinguishedName     : CN=Evgenija EF. Fedorova,OU=Rusija Office Users,OU=Office,OU=Rusija,OU=Branch Offices,DC=Alkalo\r\n                        idAD,DC=local\r\nEnabled               : True\r\nLastLogonDate         : 09.10.2023 12:59:55\r\nLockedOut             : True\r\nName                  : Evgenija EF. Fedorova\r\nObjectClass           : user\r\nObjectGUID            : 6a324df1-50b8-4a77-b225-c768b0dfd4c2\r\nPasswordExpired       : False\r\nPasswordNeverExpires  : False\r\nSamAccountName        : eovcharova\r\nSID                   : S-1-5-21-2578338701-810240250-581793511-12604\r\nUserPrincipalName     : efedorova@alkaloid.com.mk\r\n\r\nAccountExpirationDate : \r\nDistinguishedName     : CN=Ekaterina EA. Alekseeva,OU=Rusija Office Users,OU=Office,OU=Rusija,OU=Branch Offices,DC=Alka\r\n                        loidAD,DC=local\r\nEnabled               : True\r\nLastLogonDate         : 05.10.2023 6:58:26\r\nLockedOut             : True\r\nName                  : Ekaterina EA. Alekseeva\r\nObjectClass           : user\r\nObjectGUID            : 123ce775-1b44-42d8-a05e-7cb25c744084\r\nPasswordExpired       : False\r\nPasswordNeverExpires  : False\r\nSamAccountName        : ealekseeva\r\nSID                   : S-1-5-21-2578338701-810240250-581793511-12603\r\nUserPrincipalName     : ealekseeva@alkaloid.com.mk\r\n\r\n\r\n\r\n'

# bot_api = '1806115136:AAH1ItG9o8CRyjeSyfKHx5GlS5l3QPLCQYY'  # Тестовый бот
bot_api = '1456512927:AAHFhXd3v_5g3HU2XKuzplk94BnPdVwLxdU'  # Основной бот

# admin_chat = -1001897059431  # Тестовый чат -459488275
admin_chat = -439723416  # Основой чат -439723416

bot = Bot(token=bot_api)