use std::slice;

use dhad_core::wasm_api::{
    dc_doc_analyze, dc_doc_create, dc_doc_destroy, dc_doc_result_len, dc_doc_result_ptr,
    dc_doc_revision, dc_doc_update, dc_live_documents, dc_load_rules,
};

const MAGIC: u32 = 0x4441_4844;
const FORMAT_VERSION: u16 = 1;
const HEADER_SIZE: usize = 56;
const RECORD_SIZE: usize = 80;

fn u16_at(bytes: &[u8], offset: usize) -> u16 {
    u16::from_le_bytes(bytes[offset..offset + 2].try_into().unwrap())
}

fn u32_at(bytes: &[u8], offset: usize) -> u32 {
    u32::from_le_bytes(bytes[offset..offset + 4].try_into().unwrap())
}

fn i32_at(bytes: &[u8], offset: usize) -> i32 {
    i32::from_le_bytes(bytes[offset..offset + 4].try_into().unwrap())
}

fn f64_at(bytes: &[u8], offset: usize) -> f64 {
    f64::from_le_bytes(bytes[offset..offset + 8].try_into().unwrap())
}

fn string_at(bytes: &[u8], record: usize, field: usize) -> &str {
    let strings = u32_at(bytes, 40) as usize;
    let record = HEADER_SIZE + record * RECORD_SIZE;
    let offset = u32_at(bytes, record + field) as usize;
    let length = u32_at(bytes, record + field + 4) as usize;
    std::str::from_utf8(&bytes[strings + offset..strings + offset + length]).unwrap()
}

fn list_at(bytes: &[u8], start: usize, count: usize) -> Vec<&str> {
    let lists = u32_at(bytes, 36) as usize;
    let strings = u32_at(bytes, 40) as usize;
    (start..start + count)
        .map(|index| {
            let entry = lists + index * 8;
            let offset = u32_at(bytes, entry) as usize;
            let length = u32_at(bytes, entry + 4) as usize;
            std::str::from_utf8(&bytes[strings + offset..strings + offset + length]).unwrap()
        })
        .collect()
}

#[test]
fn persistent_documents_emit_versioned_packed_diagnostics_and_reject_stale_handles() {
    let rule_pack = r#"{
      "format": 1,
      "rules": [{
        "id": "PACKED_UTF8",
        "pattern": "خطا",
        "suggestions": ["خطأ", "الصواب"],
        "message": "همزة مفقودة",
        "category": "spelling",
        "severity": "error",
        "confidence": 0.95,
        "priority": 80,
        "autofix": true,
        "explanation": "اختبار ABI"
      }]
    }"#;
    assert_eq!(
        unsafe { dc_load_rules(rule_pack.as_ptr(), rule_pack.len()) },
        1
    );

    let baseline = dc_live_documents();
    let text = "هذا خطا واضح.";
    let handle = unsafe { dc_doc_create(text.as_ptr(), text.len()) };
    assert_ne!(handle, 0);
    assert_eq!(dc_live_documents(), baseline + 1);
    assert_eq!(dc_doc_revision(handle), 1);
    assert_eq!(dc_doc_result_ptr(handle), std::ptr::null());
    assert_eq!(dc_doc_result_len(handle), 0);

    assert_eq!(dc_doc_analyze(handle), 0);
    let result_ptr = dc_doc_result_ptr(handle);
    let result_len = dc_doc_result_len(handle);
    assert!(!result_ptr.is_null());
    assert!(result_len >= HEADER_SIZE + 2 * RECORD_SIZE);
    let packed = unsafe { slice::from_raw_parts(result_ptr, result_len) };

    assert_eq!(u32_at(packed, 0), MAGIC);
    assert_eq!(u16_at(packed, 4), FORMAT_VERSION);
    assert_eq!(u16_at(packed, 6) as usize, HEADER_SIZE);
    assert_eq!(u16_at(packed, 8) as usize, RECORD_SIZE);
    assert_eq!(u16_at(packed, 10), 8);
    assert_eq!(u32_at(packed, 16), 1); // raw match count
    assert_eq!(u32_at(packed, 20), 1); // resolved match count
    assert_eq!(u32_at(packed, 24), 2); // raw + resolved records
    assert_eq!(u32_at(packed, 48) as usize, packed.len());
    assert_eq!(u32_at(packed, 52), 1);

    assert_eq!(string_at(packed, 0, 0), "PACKED_UTF8");
    assert_eq!(string_at(packed, 0, 8), "spelling");
    assert_eq!(string_at(packed, 0, 16), "همزة مفقودة");
    assert_eq!(string_at(packed, 0, 24), "اختبار ABI");
    let record = HEADER_SIZE;
    assert_eq!(u32_at(packed, record + 32), 4);
    assert_eq!(u32_at(packed, record + 36), 3);
    assert!((f64_at(packed, record + 40) - 0.95).abs() < f64::EPSILON);
    assert_eq!(i32_at(packed, record + 48), 80);
    assert_eq!(packed[record + 76], 2); // error
    assert_eq!(packed[record + 77], 1); // autofix

    let replacements_start = u32_at(packed, record + 52) as usize;
    let replacements_count = u16_at(packed, record + 68) as usize;
    assert_eq!(
        list_at(packed, replacements_start, replacements_count),
        vec!["خطأ", "الصواب"]
    );

    // The resolved record must preserve all observable diagnostic fields.
    for field in [0, 8, 16, 24] {
        assert_eq!(string_at(packed, 0, field), string_at(packed, 1, field));
    }
    assert_eq!(
        &packed[HEADER_SIZE + 32..HEADER_SIZE + 52],
        &packed[HEADER_SIZE + RECORD_SIZE + 32..HEADER_SIZE + RECORD_SIZE + 52]
    );
    assert_eq!(
        &packed[HEADER_SIZE + 68..HEADER_SIZE + RECORD_SIZE],
        &packed[HEADER_SIZE + RECORD_SIZE + 68..HEADER_SIZE + 2 * RECORD_SIZE]
    );
    for (start_field, count_field) in [(52, 68), (56, 70), (60, 72), (64, 74)] {
        let raw_start = u32_at(packed, HEADER_SIZE + start_field) as usize;
        let raw_count = u16_at(packed, HEADER_SIZE + count_field) as usize;
        let resolved_start = u32_at(packed, HEADER_SIZE + RECORD_SIZE + start_field) as usize;
        let resolved_count = u16_at(packed, HEADER_SIZE + RECORD_SIZE + count_field) as usize;
        assert_eq!(raw_count, resolved_count);
        assert_eq!(
            list_at(packed, raw_start, raw_count),
            list_at(packed, resolved_start, resolved_count)
        );
    }

    let corrected = "هذا خطأ واضح.";
    assert_eq!(
        unsafe { dc_doc_update(handle, corrected.as_ptr(), corrected.len()) },
        0
    );
    assert_eq!(dc_doc_revision(handle), 2);
    assert_eq!(dc_doc_result_len(handle), 0);
    assert_eq!(dc_doc_analyze(handle), 0);
    let empty =
        unsafe { slice::from_raw_parts(dc_doc_result_ptr(handle), dc_doc_result_len(handle)) };
    assert_eq!(u32_at(empty, 16), 0);
    assert_eq!(u32_at(empty, 20), 0);
    assert_eq!(u32_at(empty, 52), 2);

    assert_eq!(dc_doc_destroy(handle), 1);
    assert_eq!(dc_live_documents(), baseline);
    assert_eq!(dc_doc_destroy(handle), 0);
    assert_eq!(dc_doc_analyze(handle), -1);
    assert_eq!(dc_doc_revision(handle), 0);
}
