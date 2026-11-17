[app]

# (str) Titre de votre application
title = JeuSoiree

# (str) Nom du package
package.name = JeuSoiree

# (str) Domaine du package (unique)
package.domain = com.hepia

# (str) Répertoire source de l'application
source.dir = .

# (list) Fichiers ou répertoires sources à inclure
source.include_exts = py,kv,spec,png,ttf,otf

# (str) Version de l'application
version = 1.0.0
icon.filename = %(source.dir)s/icon.png

# (list) Dépendances de l'application
# plyer toujours inclus — requis pour accéléromètre, GPS, vibration, etc.
requirements = python3,kivy,plyer,kivy_garden.graph

# (str) Permissions Android
android.permissions = INTERNET, VIBRATE

# (int) Version du SDK Android cible
android.api = 31

# (int) Version minimale du SDK Android
# IMPORTANT: valeur minimale 24 avec NDK r25b — en dessous, grpmodule.c
# échoue à compiler (setgrent/getgrent absents de l'API Android < 24)
android.minapi = 24

# (int) Version du NDK Android
android.ndk = 25b

# Chemin vers le SDK Android déjà installé (évite le re-téléchargement)
android.sdk_path = /home/student/.buildozer/android/platform/android-sdk
# Chemin vers le NDK Android déjà installé (évite le re-téléchargement)
android.ndk_path = /home/student/.buildozer/android/platform/android-ndk-r25b

# Ne pas vérifier les mises à jour des outils Android à chaque build
android.accept_sdk_license = True
android.skip_update = True

# (bool) Autoriser la sauvegarde
android.allow_backup = True

# (str) Orientation de l'écran
orientation = portrait

# (bool) Activer le mode plein écran
fullscreen = 0

# (list) Architectures à compiler
android.archs = arm64-v8a

[buildozer]

# (int) Niveau de log
log_level = 2

# (int) Afficher les avertissements
warn_on_root = 1
