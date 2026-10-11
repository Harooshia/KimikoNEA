# Minecraft AI Companion — CheatUtils Integration

## Dependencies

* [Zergatul/CheatUtils](https://github.com/Zergatul/cheatutils)
* Minecraft
* Python
* LM Studio
* A compatible local AI model

The CheatUtils backend runs on:

```text
http://localhost:5005/
```

The Python AI companion backend runs on:

```text
http://127.0.0.1:5001
```

Events are sent to:

```text
POST /logs
```

---

## Implementation

The Minecraft-side integration is implemented through a CheatUtils **Event Script**.

Add the following script through:

```text
http://localhost:5005/
→ Scriptings
→ Event Scripts Module
```

```javascript
let companionEnabled = false;

int LOW_HEALTH = 10;
int LOW_FOOD = 8;

let healthAlertActive = false;
let foodAlertActive = false;

// ======================
// CHAT MESSAGES
// ======================

events.onChatMessage((msg) => {

    int index = msg.indexOf("> ");

    if (index != -1) {
        msg = msg.substring(index + 2);
    }

    if (msg == "!on") {
        companionEnabled = true;
        ui.overlayMessage("AI Companion Enabled");
        return;
    }

    if (msg == "!off") {
        companionEnabled = false;
        ui.overlayMessage("AI Companion Disabled");
        return;
    }

    if (!companionEnabled || player == null) {
        return;
    }

    string biome = player.getBiome();
    string dimension = game.dimension.get();

    string json =
        "{"
        + "\"reason\":\"chat\","
        + "\"username\":\"" + game.getUserName() + "\","
        + "\"message\":\"" + msg + "\","
        + "\"biome\":\"" + biome + "\","
        + "\"dimension\":\"" + dimension + "\","
        + "\"daytime\":" + game.getDayTime() + ","
        + "\"players_online\":" + game.getOnlinePlayers().length + ","
        + "\"is_raining\":" + game.isRaining() + ","
        + "\"is_thundering\":" + game.isThundering() + ","
        + "\"minecraft_version\":\"" + game.getVersion() + "\""
        + "}";

    http.send(
        HttpRequest.createBuilder()
            .post(json)
            .url("http://127.0.0.1:5001/logs")
            .header("Content-Type", "application/json")
            .build()
    );
});

// ======================
// HEALTH + FOOD CHECK
// ======================

events.onTickEnd(() => {

    if (!companionEnabled || player == null) {
        return;
    }

    int health = player.getHealth();
    int food = player.getFood();

    string biome = player.getBiome();
    string dimension = game.dimension.get();

    // LOW HEALTH
    if (health <= LOW_HEALTH && healthAlertActive == false) {

        healthAlertActive = true;

        string json =
            "{"
            + "\"reason\":\"low_health\","
            + "\"username\":\"" + game.getUserName() + "\","
            + "\"message\":\"Player health low: " + health + "\","
            + "\"biome\":\"" + biome + "\","
            + "\"dimension\":\"" + dimension + "\""
            + "}";

        http.send(
            HttpRequest.createBuilder()
                .post(json)
                .url("http://127.0.0.1:5001/logs")
                .header("Content-Type", "application/json")
                .build()
        );
    }

    if (health > LOW_HEALTH) {
        healthAlertActive = false;
    }

    // LOW FOOD
    if (food <= LOW_FOOD && foodAlertActive == false) {

        foodAlertActive = true;

        string json =
            "{"
            + "\"reason\":\"low_food\","
            + "\"username\":\"" + game.getUserName() + "\","
            + "\"message\":\"Player hunger low: " + food + "\","
            + "\"biome\":\"" + biome + "\","
            + "\"dimension\":\"" + dimension + "\""
            + "}";

        http.send(
            HttpRequest.createBuilder()
                .post(json)
                .url("http://127.0.0.1:5001/logs")
                .header("Content-Type", "application/json")
                .build()
        );
    }

    if (food > LOW_FOOD) {
        foodAlertActive = false;
    }
});
```

## Key Features

### AI Companion Toggle

The companion can be enabled or disabled directly through Minecraft chat:

```text
!on
```

```text
!off
```

This prevents the companion from processing events when it is not needed.

### Chat Integration

When enabled, chat messages are sent to the Python backend along with useful Minecraft context:

* Username
* Message
* Biome
* Dimension
* Time of day
* Online player count
* Rain status
* Thunderstorm status
* Minecraft version

### Health Monitoring

The script automatically detects when the player's health falls to **10 or below** and sends an alert to the backend.

The alert only triggers once until the player's health recovers, preventing repeated requests every game tick.

### Hunger Monitoring

The same system monitors food level and sends an event when it reaches **8 or below**.

Like the health system, the alert resets once the player's food level rises above the threshold.

### Context-Aware Events

All events are categorised using a `reason` field, allowing the Python backend to distinguish between different types of events:

```text
chat
low_health
low_food
```

This provides the AI with both **conversation data and real-time Minecraft context**, forming the foundation for a more context-aware local AI companion.
