function toPositiveInt(value, fallback) {
    const parsed = Number.parseInt(value, 10)
    return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback
}

function toPositiveFloat(value, fallback) {
    const parsed = Number.parseFloat(value)
    return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback
}

function randomBetween(min, max) {
    return Math.floor(Math.random() * (max - min + 1)) + min
}

function randomFloatBetween(min, max) {
    return Number((Math.random() * (max - min) + min).toFixed(2))
}

export function resolveAntiFloodConfig(config = {}) {
    const enabled = config.anti_flood_enabled !== false
    const legacyEvery = toPositiveInt(config.anti_flood_pause_every, 50)
    const everyMin = toPositiveInt(config.anti_flood_pause_every_min, legacyEvery)
    const everyMax = toPositiveInt(config.anti_flood_pause_every_max, legacyEvery)
    const lowerEvery = Math.min(everyMin, everyMax)
    const upperEvery = Math.max(everyMin, everyMax)
    const legacyPauseDuration = toPositiveFloat(config.anti_flood_pause_duration, 2)
    const durationMin = toPositiveFloat(config.anti_flood_pause_duration_min, legacyPauseDuration)
    const durationMax = toPositiveFloat(config.anti_flood_pause_duration_max, legacyPauseDuration)
    const lowerDuration = Math.min(durationMin, durationMax)
    const upperDuration = Math.max(durationMin, durationMax)

    return {
        pause_every: enabled ? randomBetween(lowerEvery, upperEvery) : 0,
        pause_duration: enabled ? randomFloatBetween(lowerDuration, upperDuration) : 0,
    }
}
