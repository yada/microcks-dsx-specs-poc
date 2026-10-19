use carbide_uuid::machine::{HostMachineId, MachineId, MachineIdSource, MachineType};
use model::machine::ManagedHostState;
use serde::Serialize;

// Same shape as api-core's mqtt_state_change_hook::message::ManagedHostStateMessage.
#[derive(Serialize)]
struct Msg<'a> {
    machine_id: &'a HostMachineId,
    timestamp: chrono::DateTime<chrono::Utc>,
    managed_host_state: &'a ManagedHostState,
}

#[allow(deprecated)]
fn main() {
    let id: HostMachineId = MachineId::new(MachineIdSource::ProductBoardChassisSerial, [0; 32], MachineType::Host)
        .try_into()
        .unwrap();
    let samples: Vec<String> = serde_json::from_str(&std::fs::read_to_string("samples.json").unwrap()).unwrap();
    let ts = chrono::DateTime::parse_from_rfc3339("2026-10-05T18:00:00Z").unwrap().to_utc();
    let (mut ok, mut bad) = (0, 0);
    for s in samples {
        match serde_json::from_str::<ManagedHostState>(&s) {
            Ok(st) => {
                ok += 1;
                println!("{}", serde_json::to_string(&Msg { machine_id: &id, timestamp: ts, managed_host_state: &st }).unwrap());
            }
            Err(e) => {
                bad += 1;
                eprintln!("REJECTED {s} :: {e}");
            }
        }
    }
    eprintln!("accepted={ok} rejected={bad}");
}
