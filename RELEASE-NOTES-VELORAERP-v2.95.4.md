# VeloraERP 2.95.4 - clearer pricing, and a guide you can open from the App Hub
- **Two averages**: *Simple Average of Last Purchases* (plain mean of the last 3 to 5 receipt prices) and *Weighted Average of Last Purchases* (counts quantities) are now separate choices for Cost Used for Pricing, at Inventory Settings, Item Group or Item level. The Highest of These (Safest) rule considers both. A value saved as "Average of Last Purchases" in 2.95.3 is read as the weighted one.
- **Explain Pricing tells the story** on Sales Orders and Sales Invoices: the cost method and where it was set, every method's cost, the margin and where it came from, how the price was calculated (markup or margin, unit and currency conversion, rounding), the profit per unit, and the lowest allowed rate. The same text comes from the API (`narrative`), so a report or print can use it.
- The user manual opens with a welcome and is available from the App Hub (How-to guide), and the pricing section describes the new choices.

Limits: the narrative describes one item line at a time. Nothing was run on a live server.
