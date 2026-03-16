.pragma library

var radius = 12

function palette(isDark) {
    if (isDark) {
        return {
            bg: "#111827",
            bgElevated: "#0f172a",
            bgCard: "#16213e",
            bgCardHover: "#1f3460",
            bgSidebar: "#0b1220",
            bgInput: "#111827",
            bgSubtle: "#0f1525",
            accent: "#00d4aa",
            accentHover: "#00ffc8",
            accentDim: "#0d2e26",
            textPrimary: "#edf2f7",
            textSecondary: "#9aa4b6",
            textDim: "#6f7b90",
            border: "#263246",
            danger: "#ff6b6b",
            dangerBg: "#5b1f26",
            success: "#00d4aa",
            warning: "#ffb347",
            tooltipBg: "#314055",
            tooltipText: "#f8fafc"
        }
    }

    return {
        bg: "#f5f7fb",
        bgElevated: "#ffffff",
        bgCard: "#ffffff",
        bgCardHover: "#edf3ff",
        bgSidebar: "#e9eef7",
        bgInput: "#ffffff",
        bgSubtle: "#f0f4fa",
        accent: "#0ea5a4",
        accentHover: "#14b8a6",
        accentDim: "#d9f4ee",
        textPrimary: "#142033",
        textSecondary: "#526077",
        textDim: "#76839a",
        border: "#d5ddeb",
        danger: "#c73c4c",
        dangerBg: "#fbe3e7",
        success: "#0ea5a4",
        warning: "#b7791f",
        tooltipBg: "#202938",
        tooltipText: "#f8fafc"
    }
}
