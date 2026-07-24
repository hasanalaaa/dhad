mod file_commands;
mod native_commands;
mod tray;

#[cfg(target_os = "macos")]
fn apply_platform_window_effects(app: &tauri::App) -> tauri::Result<()> {
    use tauri::{
        window::{Effect, EffectState, EffectsBuilder},
        Manager,
    };

    if let Some(window) = app.get_webview_window("mini-assistant") {
        window.set_effects(
            EffectsBuilder::new()
                .effect(Effect::HudWindow)
                .state(EffectState::FollowsWindowActiveState)
                .radius(18.0)
                .build(),
        )?;
    }
    Ok(())
}

#[cfg(target_os = "windows")]
fn apply_platform_window_effects(app: &tauri::App) -> tauri::Result<()> {
    use tauri::{
        window::{Effect, EffectsBuilder},
        Manager,
    };

    if let Some(window) = app.get_webview_window("mini-assistant") {
        window.set_effects(EffectsBuilder::new().effect(Effect::Mica).build())?;
    }
    Ok(())
}

#[cfg(not(any(target_os = "macos", target_os = "windows")))]
fn apply_platform_window_effects(_app: &tauri::App) -> tauri::Result<()> {
    Ok(())
}

#[cfg(any(target_os = "macos", target_os = "windows"))]
fn quick_assistant_shortcut() -> tauri_plugin_global_shortcut::Shortcut {
    use tauri_plugin_global_shortcut::{Code, Modifiers, Shortcut};
    Shortcut::new(Some(Modifiers::ALT), Code::Space)
}

#[cfg(any(target_os = "macos", target_os = "windows"))]
fn quick_assistant_fallback_shortcut() -> tauri_plugin_global_shortcut::Shortcut {
    use tauri_plugin_global_shortcut::{Code, Modifiers, Shortcut};
    Shortcut::new(Some(Modifiers::CONTROL | Modifiers::ALT), Code::Space)
}

#[cfg(any(target_os = "macos", target_os = "windows"))]
fn is_quick_assistant_shortcut(
    shortcut: &tauri_plugin_global_shortcut::Shortcut,
) -> bool {
    shortcut == &quick_assistant_shortcut() || shortcut == &quick_assistant_fallback_shortcut()
}

pub fn run() {
    let builder = tauri::Builder::default().plugin(tauri_plugin_dialog::init());

    #[cfg(any(target_os = "macos", target_os = "windows"))]
    let builder = {
        use tauri_plugin_global_shortcut::ShortcutState;
        builder.plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, shortcut, event| {
                    if is_quick_assistant_shortcut(shortcut)
                        && event.state() == ShortcutState::Pressed
                    {
                        tray::schedule_toggle_mini_window(app);
                    }
                })
                .build(),
        )
    };

    builder
        .setup(|app| {
            tray::create_system_tray(app)?;

            if let Err(error) = apply_platform_window_effects(app) {
                // A compositor effect must never prevent the application from launching.
                eprintln!("failed to apply platform window effects: {error}");
            }

            #[cfg(any(target_os = "macos", target_os = "windows"))]
            {
                use tauri_plugin_global_shortcut::GlobalShortcutExt;
                if let Err(primary_error) =
                    app.global_shortcut().register(quick_assistant_shortcut())
                {
                    if let Err(fallback_error) = app
                        .global_shortcut()
                        .register(quick_assistant_fallback_shortcut())
                    {
                        // Both failures are non-fatal because the tray action remains available.
                        eprintln!(
                            "failed to register quick-assistant shortcuts: primary={primary_error}; fallback={fallback_error}"
                        );
                    }
                }
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if matches!(window.label(), "main" | "mini-assistant") {
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            native_commands::analyze_text_native,
            native_commands::paraphrase_native,
            native_commands::get_system_info,
            file_commands::read_document_file,
            file_commands::write_document_file,
            tray::toggle_mini_assistant,
            tray::hide_mini_assistant,
            tray::open_main_window,
        ])
        .run(tauri::generate_context!())
        .expect("failed to run the Dhad desktop application");
}
