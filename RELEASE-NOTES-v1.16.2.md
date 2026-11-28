# Velora 1.16.2 - a how-to guide for every application
- Each application can ship its own how-to guide. The app names it in `hooks.py` (`app_guide = "docs/NAME-v*.html"`); Velora serves it at `/guide/<app>` as one self-contained page, no sign-in needed, like `/tutorial`. Only .html files inside the app's own package are ever served.
- The **App Hub** has a "How-to guides" row (framework manual plus every installed application's guide), and each hub opens with a welcome line and a "How-to guide" link. The **Welcome** page shows a How-to link beside each installed app.
- The framework manual opens with a welcome and links to the other guides.
- Forms show multi-line explanations properly (the Explain Pricing text).
