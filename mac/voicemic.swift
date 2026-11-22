// Walkie: Mikrofon mit macOS-Sprachverarbeitung (Echo- und Rauschunterdrückung) aufnehmen
// und als 16 kHz / mono / s16le auf stdout schreiben. Meldungen gehen auf stderr.
// Idee und Rückfallstufen aus GodTerm: erst mit Sprachverarbeitung, sonst ohne (die scheitert
// z. B. bei Bluetooth-Kopfhörern im Telefonmodus). Bei Gerätewechsel neu starten (max. 20 Mal).
// Ende: SIGTERM/SIGINT oder wenn der Leser stdout schließt (SIGPIPE).
import AVFoundation
import Foundation

let target = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16000, channels: 1,
                           interleaved: true)!
let out = FileHandle.standardOutput
var engine = AVAudioEngine()
var restarts = 0

func log(_ text: String) {
    FileHandle.standardError.write((text + "\n").data(using: .utf8)!)
}

func start(voiceProcessing: Bool) -> Bool {
    engine = AVAudioEngine()
    let input = engine.inputNode
    if voiceProcessing {
        do {
            try input.setVoiceProcessingEnabled(true)
        } catch {
            log("voice-processing nicht möglich: \(error)")
            return false
        }
        if #available(macOS 14.0, *) {
            // andere Wiedergabe (die eigene Stimme des Walkies) nicht leiser drehen
            input.voiceProcessingOtherAudioDuckingConfiguration =
                AVAudioVoiceProcessingOtherAudioDuckingConfiguration(enableAdvancedDucking: false,
                                                                      duckingLevel: .min)
        }
    }
    let format = input.outputFormat(forBus: 0)
    guard format.sampleRate > 0, let converter = AVAudioConverter(from: format, to: target) else {
        log("kein Eingabegerät")
        return false
    }
    input.installTap(onBus: 0, bufferSize: 1600, format: format) { buffer, _ in
        let capacity = AVAudioFrameCount(Double(buffer.frameLength) * target.sampleRate
                                         / format.sampleRate) + 64
        guard let converted = AVAudioPCMBuffer(pcmFormat: target, frameCapacity: capacity) else { return }
        var fed = false
        var error: NSError?
        converter.convert(to: converted, error: &error) { _, status in
            if fed {
                status.pointee = .noDataNow
                return nil
            }
            fed = true
            status.pointee = .haveData
            return buffer
        }
        if let samples = converted.int16ChannelData, converted.frameLength > 0 {
            out.write(Data(bytes: samples[0], count: Int(converted.frameLength) * 2))
        }
    }
    do {
        try engine.start()
        log("aufnahme läuft (sprachverarbeitung: \(voiceProcessing))")
        return true
    } catch {
        log("start fehlgeschlagen (sprachverarbeitung: \(voiceProcessing)): \(error)")
        input.removeTap(onBus: 0)
        return false
    }
}

func startBest() {
    if !start(voiceProcessing: true) && !start(voiceProcessing: false) {
        log("kein Mikrofon")
        exit(3)
    }
}

NotificationCenter.default.addObserver(forName: .AVAudioEngineConfigurationChange, object: nil,
                                       queue: .main) { _ in
    restarts += 1
    guard restarts <= 20 else {
        log("zu viele Gerätewechsel")
        exit(4)
    }
    engine.inputNode.removeTap(onBus: 0)
    engine.stop()
    startBest()
}

signal(SIGINT) { _ in exit(0) }
signal(SIGTERM) { _ in exit(0) }
startBest()
RunLoop.main.run()
