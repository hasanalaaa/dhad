use std::{
    fs::{self, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

use serde::{Deserialize, Serialize};

const MAX_DOCUMENT_BYTES: u64 = 64 * 1024 * 1024;
const ALLOWED_EXTENSIONS: &[&str] = &["txt", "md", "docx", "pdf"];

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ReadDocumentRequest {
    path: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeDocumentFile {
    name: String,
    path: String,
    extension: String,
    size_bytes: u64,
    bytes: Vec<u8>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct WriteDocumentRequest {
    path: String,
    format: String,
    bytes: Vec<u8>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeWriteResponse {
    path: String,
    size_bytes: usize,
}

fn normalized_extension(path: &Path) -> Option<String> {
    path.extension()
        .and_then(|extension| extension.to_str())
        .map(|extension| extension.to_ascii_lowercase())
}

fn validate_format(format: &str) -> Result<String, String> {
    let format = format.trim().trim_start_matches('.').to_ascii_lowercase();
    if ALLOWED_EXTENSIONS.contains(&format.as_str()) {
        Ok(format)
    } else {
        Err("unsupported document format".to_string())
    }
}

fn validated_read_path(path: &str) -> Result<PathBuf, String> {
    let path = PathBuf::from(path);
    let extension = normalized_extension(&path)
        .ok_or_else(|| "the selected file has no supported extension".to_string())?;
    validate_format(&extension)?;
    let metadata = fs::metadata(&path).map_err(|error| error.to_string())?;
    if !metadata.is_file() {
        return Err("the selected path is not a regular file".to_string());
    }
    if metadata.len() > MAX_DOCUMENT_BYTES {
        return Err("the selected document exceeds the 64 MiB safety limit".to_string());
    }
    Ok(path)
}

fn resolved_write_path(path: &str, format: &str) -> Result<PathBuf, String> {
    let format = validate_format(format)?;
    let mut path = PathBuf::from(path);
    match normalized_extension(&path) {
        Some(extension) if extension == format => {}
        Some(_) => {
            return Err(
                "the selected filename extension does not match the export format".to_string(),
            )
        }
        None => {
            path.set_extension(format);
        }
    }
    if path.file_name().is_none() {
        return Err("the selected export path is invalid".to_string());
    }
    if let Some(parent) = path.parent() {
        if !parent.as_os_str().is_empty() {
            if !parent.exists() {
                return Err("the selected export directory does not exist".to_string());
            }
            if !parent.is_dir() {
                return Err("the selected export parent is not a directory".to_string());
            }
        }
    }
    Ok(path)
}

fn sibling_staging_path(path: &Path, role: &str) -> Result<PathBuf, String> {
    let parent = path.parent().unwrap_or_else(|| Path::new("."));
    let file_name = path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| "the selected filename is not valid UTF-8".to_string())?;
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| error.to_string())?
        .as_nanos();
    Ok(parent.join(format!(
        ".{file_name}.dhad-{role}-{}-{nonce}",
        std::process::id()
    )))
}

fn temporary_export_path(path: &Path) -> Result<PathBuf, String> {
    sibling_staging_path(path, "write.tmp")
}

#[cfg(target_os = "windows")]
fn backup_export_path(path: &Path) -> Result<PathBuf, String> {
    sibling_staging_path(path, "rollback.bak")
}

fn commit_export(temp_path: &Path, destination: &Path) -> Result<(), String> {
    #[cfg(target_os = "windows")]
    {
        let destination_existed = destination.exists();
        let backup_path = destination_existed
            .then(|| backup_export_path(destination))
            .transpose()?;

        if let Some(backup_path) = backup_path.as_ref() {
            fs::rename(destination, backup_path).map_err(|error| error.to_string())?;
        }

        match fs::rename(temp_path, destination) {
            Ok(()) => {
                if let Some(backup_path) = backup_path {
                    let _ = fs::remove_file(backup_path);
                }
                Ok(())
            }
            Err(error) => {
                if let Some(backup_path) = backup_path {
                    let _ = fs::rename(backup_path, destination);
                }
                Err(error.to_string())
            }
        }
    }

    #[cfg(not(target_os = "windows"))]
    {
        fs::rename(temp_path, destination).map_err(|error| error.to_string())
    }
}

fn read_document_file_blocking(request: ReadDocumentRequest) -> Result<NativeDocumentFile, String> {
    let path = validated_read_path(&request.path)?;
    let bytes = fs::read(&path).map_err(|error| error.to_string())?;
    if bytes.len() as u64 > MAX_DOCUMENT_BYTES {
        return Err("the selected document exceeds the 64 MiB safety limit".to_string());
    }
    let extension = normalized_extension(&path).unwrap_or_default();
    let name = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| "the selected filename is not valid UTF-8".to_string())?
        .to_string();

    Ok(NativeDocumentFile {
        name,
        path: path.to_string_lossy().into_owned(),
        extension,
        size_bytes: bytes.len() as u64,
        bytes,
    })
}

fn write_document_file_blocking(
    request: WriteDocumentRequest,
) -> Result<NativeWriteResponse, String> {
    if request.bytes.len() as u64 > MAX_DOCUMENT_BYTES {
        return Err("the exported document exceeds the 64 MiB safety limit".to_string());
    }
    let path = resolved_write_path(&request.path, &request.format)?;
    let temp_path = temporary_export_path(&path)?;
    let write_result = (|| -> Result<(), String> {
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&temp_path)
            .map_err(|error| error.to_string())?;
        file.write_all(&request.bytes)
            .map_err(|error| error.to_string())?;
        file.sync_all().map_err(|error| error.to_string())?;
        drop(file);
        commit_export(&temp_path, &path)
    })();

    if write_result.is_err() {
        let _ = fs::remove_file(&temp_path);
    }
    write_result?;

    Ok(NativeWriteResponse {
        path: path.to_string_lossy().into_owned(),
        size_bytes: request.bytes.len(),
    })
}

#[tauri::command]
pub async fn read_document_file(request: ReadDocumentRequest) -> Result<NativeDocumentFile, String> {
    tauri::async_runtime::spawn_blocking(move || read_document_file_blocking(request))
        .await
        .map_err(|error| error.to_string())?
}

#[tauri::command]
pub async fn write_document_file(
    request: WriteDocumentRequest,
) -> Result<NativeWriteResponse, String> {
    tauri::async_runtime::spawn_blocking(move || write_document_file_blocking(request))
        .await
        .map_err(|error| error.to_string())?
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn write_path_appends_missing_extension() {
        let path = std::env::temp_dir().join("dhad-document");
        let path = resolved_write_path(path.to_string_lossy().as_ref(), "txt").expect("valid path");
        assert_eq!(path.extension().and_then(|value| value.to_str()), Some("txt"));
    }

    #[test]
    fn write_path_rejects_extension_mismatch() {
        let path = std::env::temp_dir().join("dhad-document.pdf");
        assert!(resolved_write_path(path.to_string_lossy().as_ref(), "docx").is_err());
    }

    #[test]
    fn temporary_export_stays_next_to_destination() {
        let destination = std::env::temp_dir().join("dhad-export.md");
        let temporary = temporary_export_path(&destination).expect("temporary path");
        assert_eq!(temporary.parent(), destination.parent());
        assert_ne!(temporary, destination);
    }
}
