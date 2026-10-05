import SwiftUI
import AppKit
import Darwin
import UniformTypeIdentifiers

let accent = Color(red: 0.02, green: 0.43, blue: 0.45)
let pages = ["Overview", "Brief", "Generate", "Style", "Prompts", "Outline", "Bibliography", "Data", "Inspiration", "Abstract", "Manuscript", "Rewrite", "Repair", "Export", "Settings"]
let symbols = ["square.grid.2x2", "pencil.and.list.clipboard", "sparkles", "paintbrush.pointed", "text.quote", "list.bullet.indent", "books.vertical", "tablecells", "doc.on.doc", "text.alignleft", "book.closed", "arrow.triangle.2.circlepath", "wrench.and.screwdriver", "square.and.arrow.up", "slider.horizontal.3"]

func validRecentProjects(_ paths: [String]) -> [String] {
    var seen=Set<String>()
    return Array(paths.filter { path in
        let url=URL(fileURLWithPath:path).standardizedFileURL
        return FileManager.default.fileExists(atPath:url.appendingPathComponent("brief.json").path) && seen.insert(url.path).inserted
    }.prefix(20))
}
func loadRecentProjects() -> [String] {
    let paths=validRecentProjects(UserDefaults.standard.stringArray(forKey:"recentProjects") ?? [])
    UserDefaults.standard.set(paths,forKey:"recentProjects")
    return paths
}

@MainActor final class Studio: ObservableObject {
    @Published var page = "Overview"
    @Published var generationKind = "titles"
    @Published var generationText = ""
    @Published var manuscriptRepairInstructions = ""
    @Published var project: [String: Any] = [:]
    @Published var brief: [String: Any] = [:]
    @Published var provider = "openai"
    @Published var model = "gpt-6-luna"
    @Published var endpoint = ""
    @Published var openAIKey = ""
    @Published var arcKey = ""
    @Published var models: [String] = []
    @Published var modelFilter = ""
    @Published var busy = false
    @Published var stopping = false
    @Published var activity: [String] = []
    @Published var lastMessage = "Ready"
    @Published var error: String?
    @Published var abstractText = ""
    @Published var fieldDrafts: [String:String] = [:]
    @Published var briefDirty = false
    @Published var abstractDirty = false
    @Published var newProject = false
    @Published var showRenameProject = false
    @Published var showBibliography = false
    @Published var bibliographyText = ""
    @Published var bibliographyName = ""
    @Published var showReuse = false
    @Published var reuseSource = ""
    @Published var analyses: [[String: Any]] = []
    @Published var selectedAnalyses: Set<String> = []
    @Published var recent: [String] = loadRecentProjects()
    var bundledEngine: String? {
        guard Bundle.main.object(forInfoDictionaryKey:"KOALAStandalone") as? Bool == true else { return nil }
        return (Bundle.main.resourcePath ?? "")+"/engine/koala-engine"
    }
    @Published var root: String = Bundle.main.object(forInfoDictionaryKey:"KOALAStandalone") as? Bool == true ? NSHomeDirectory()+"/Documents/KOALA" : (UserDefaults.standard.string(forKey: "engineRoot") ?? (Bundle.main.object(forInfoDictionaryKey: "KOALAProjectRoot") as? String ?? NSHomeDirectory()+"/VIBES/KOALA"))
    var process: Process?
    var folder: String { project["folder"] as? String ?? "" }
    func projectName(_ path:String) -> String {
        if path == folder, let name=project["project_name"] as? String { return name }
        if let data=try? Data(contentsOf:URL(fileURLWithPath:path).appendingPathComponent(".koala-project.json")), let metadata=(try? JSONSerialization.jsonObject(with:data)) as? [String:Any], let name=metadata["name"] as? String, !name.isEmpty { return name }
        return URL(fileURLWithPath:path).lastPathComponent
    }
    var article: [String: Any] { project["article"] as? [String: Any] ?? [:] }
    var sections: [[String: Any]] { article["sections"] as? [[String: Any]] ?? [] }
    var documents: [[String: Any]] { (article["inspiration"] as? [String: Any])?["documents"] as? [[String: Any]] ?? [] }
    var isBook: Bool { brief["project_type"] as? String == "book" }
    var dirty: Bool { briefDirty || abstractDirty }
    var settings: [String: Any] { ["provider": provider, "model": model, "base_url": endpoint.isEmpty ? NSNull() : endpoint] }
    var activeKey: Binding<String> { Binding(get: { self.provider == "openai" ? self.openAIKey : self.arcKey }, set: { if self.provider == "openai" { self.openAIKey = $0 } else { self.arcKey = $0 } }) }
    func value(_ key: String) -> String {
        if let array = brief[key] as? [String] { return array.joined(separator: "\n") }
        if brief[key] is NSNull { return "" }
        return brief[key].map { String(describing: $0) } ?? ""
    }
    func binding(_ key: String, list: Bool = false, number: Bool = false) -> Binding<String> {
        Binding(get: { self.fieldDrafts[key] ?? self.value(key) }, set: { text in
            self.fieldDrafts[key] = text
            if list { self.brief[key] = text.components(separatedBy: CharacterSet(charactersIn: ";\n")).map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty } }
            else if number { self.brief[key] = text.isEmpty && key == "citation_target" ? NSNull() : (Int(text) as Any? ?? text) }
            else { self.brief[key] = text }
            self.briefDirty = true
        })
    }
    func log(_ line: String) { activity.append(line); if activity.count > 1500 { activity.removeFirst(activity.count-1500) }; lastMessage = line }
    func apply(_ data: [String: Any]) {
        guard data["folder"] != nil else { return }
        let changedProject=(data["folder"] as? String ?? "") != folder
        project = data; brief = data["brief"] as? [String: Any] ?? [:]
        if changedProject || manuscriptRepairInstructions.isEmpty {
            manuscriptRepairInstructions=(article["manuscript_repair"] as? [String:Any])?["instructions"] as? String ?? ""
        }
        refreshProposal()
        let config = data["settings"] as? [String: Any] ?? [:]
        provider = config["provider"] as? String ?? "openai"; model = config["model"] as? String ?? "gpt-6-luna"
        endpoint = config["base_url"] as? String ?? ""
        abstractText = article["abstract"] as? String ?? ""
        briefDirty = false; abstractDirty = false; fieldDrafts = [:]
        recent.removeAll { $0 == folder }; recent.insert(folder, at: 0); recent = validRecentProjects(recent)
        UserDefaults.standard.set(recent, forKey: "recentProjects")
    }
    func refreshProposal() {
        let state=project["development"] as? [String:Any] ?? [:]
        let proposals=state["proposals"] as? [String:[String:Any]] ?? [:]
        generationText=proposals[generationKind]?["text"] as? String ?? ""
    }
    func mayLeave() -> Bool {
        guard dirty else { return true }
        let alert = NSAlert(); alert.messageText = "Discard unsaved edits?"; alert.informativeText = "Save your brief or abstract first to keep these changes."
        alert.addButton(withTitle: "Keep Editing"); alert.addButton(withTitle: "Discard Edits")
        return alert.runModal() == .alertSecondButtonReturn
    }
    func directory(prompt: String) -> URL? {
        let panel = NSOpenPanel(); panel.canChooseDirectories = true; panel.canChooseFiles = false; panel.canCreateDirectories = true
        panel.prompt = prompt; return panel.runModal() == .OK ? panel.url : nil
    }
    func deleteProject() {
        guard !busy, !folder.isEmpty else { return }
        let url=URL(fileURLWithPath:folder).standardizedFileURL.resolvingSymlinksInPath()
        let engine=URL(fileURLWithPath:root).standardizedFileURL.resolvingSymlinksInPath().path
        guard url.path != "/", url.path != NSHomeDirectory(), url.path != engine,
              !engine.hasPrefix(url.path+"/"),
              FileManager.default.fileExists(atPath:url.appendingPathComponent("brief.json").path) else {
            error="This folder cannot be deleted as a KOALA project."; return
        }
        let alert=NSAlert()
        alert.messageText="Are you sure you want to delete this project?"
        alert.informativeText="This moves “"+projectName(folder)+"” and all files inside its project folder to the Trash, including manuscripts, exports, imported data, and revision backups. Original files linked from outside the project folder are kept.\n\n"+url.path
        alert.alertStyle = .warning
        alert.addButton(withTitle:"Cancel")
        alert.addButton(withTitle:"Delete Project")
        guard alert.runModal() == .alertSecondButtonReturn else { return }
        let descriptor=Darwin.open(url.appendingPathComponent(".koala-desktop.lock").path,O_CREAT|O_RDWR,0o600)
        guard descriptor >= 0 else { error="Cannot access the project lock."; return }
        defer { Darwin.close(descriptor) }
        guard flock(descriptor,LOCK_EX|LOCK_NB) == 0 else { error="Another operation is using this project. Stop it before deleting."; return }
        defer { flock(descriptor,LOCK_UN) }
        do {
            try FileManager.default.trashItem(at:url,resultingItemURL:nil)
            recent.removeAll { URL(fileURLWithPath:$0).standardizedFileURL.resolvingSymlinksInPath().path == url.path || $0 == folder }
            UserDefaults.standard.set(recent,forKey:"recentProjects")
            project=[:];brief=[:];briefDirty=false;abstractDirty=false;fieldDrafts=[:]
            abstractText="";generationText="";manuscriptRepairInstructions="";page="Overview"
            log("Project moved to Trash.")
        } catch { self.error="Could not delete the project: "+error.localizedDescription }
    }
    func openProject() {
        guard !busy, mayLeave(), let url = directory(prompt: "Open Project") else { return }
        run("load", extra: ["folder":url.path])
    }
    func openRecent(_ path: String) { guard !busy, mayLeave() else { return }; run("load", extra: ["folder":path]) }
    func requireSaved() -> Bool {
        if dirty { error = "Save your brief or abstract edits before starting this operation."; return false }
        return true
    }
    func inference(_ action: String, extra: [String: Any] = [:]) {
        guard requireSaved() else { return }
        let key = provider == "openai" ? openAIKey : arcKey
        if key.isEmpty && ProcessInfo.processInfo.environment[provider == "openai" ? "OPENAI_API_KEY" : "ARC_API_KEY"] == nil {
            page = "Settings"; error = "Enter your API key in Settings, then return to this step."; return
        }
        run(action, extra: extra)
    }
    func addDocuments() {
        guard requireSaved() else { return }
        let panel = NSOpenPanel(); panel.allowsMultipleSelection = true
        panel.allowedContentTypes = [.pdf, .rtf, .plainText, .html, UTType(filenameExtension:"docx")!]; panel.prompt = "Analyze Documents"
        if panel.runModal() == .OK { inference("ingest", extra:["documents":panel.urls.map(\.path)]) }
    }
    func chooseBibliography() {
        guard !busy, requireSaved() else { return }
        let panel=NSOpenPanel(); panel.allowedContentTypes=[.pdf,.plainText,UTType(filenameExtension:"docx")!,UTType(filenameExtension:"md")!]
        panel.prompt="Review Bibliography"
        if panel.runModal() == .OK, let url=panel.url {
            run("read_bibliography",extra:["path":url.path]) { data in
                self.bibliographyText=data["text"] as? String ?? ""
                self.bibliographyName=data["name"] as? String ?? "Bibliography"
                self.showBibliography=true
            }
        }
    }
    func chooseOutline() {
        guard !busy else { return }
        let panel=NSOpenPanel(); panel.allowedContentTypes=[.pdf,.plainText,UTType(filenameExtension:"docx")!,UTType(filenameExtension:"md")!]
        panel.prompt="Import Chapter Outline"
        if panel.runModal() == .OK, let url=panel.url {
            run("read_outline",extra:["path":url.path]) { data in
                self.binding("chapter_outline").wrappedValue=data["text"] as? String ?? ""
                if let count=data["chapter_count"] as? Int { self.binding("chapter_count",number:true).wrappedValue=String(count) }
                self.log("Outline imported. Review the text and Save brief to apply it.")
            }
        }
    }
    func chooseReuse() {
        guard requireSaved(), let url = directory(prompt:"Choose Source Project") else { return }
        reuseSource = url.path; selectedAnalyses = []
        run("reuse_list", extra:["source":url.path]) { data in self.analyses = data["analyses"] as? [[String:Any]] ?? []; self.showReuse = true }
    }
    func chooseAuthors() {
        let panel=NSOpenPanel(); panel.allowedContentTypes=[.plainText]; panel.prompt="Import Authors"
        if panel.runModal() == .OK, let url=panel.url {
            do { let text=try String(contentsOf:url,encoding:.utf8); binding("important_authors",list:true).wrappedValue=text }
            catch { self.error=error.localizedDescription }
        }
    }
    func stop() { guard let process, process.isRunning else { return }; stopping = true; lastMessage = "Stopping… saving the last completed checkpoint"; process.interrupt() }
    func run(_ action: String, extra: [String: Any] = [:], completion: (([String:Any])->Void)? = nil) {
        guard !busy else { return }
        let executable = bundledEngine ?? (root + "/.venv/bin/python")
        guard FileManager.default.isExecutableFile(atPath:executable) else { page="Settings"; error="KOALA’s Python environment was not found. Choose the KOALA project folder in Settings."; return }
        var request: [String:Any] = ["action":action,"folder":folder,"settings":settings]
        for (key,value) in extra { request[key]=value }
        guard let input = try? JSONSerialization.data(withJSONObject:request) else { error="The request could not be encoded."; return }
        let task=Process(), out=Pipe(), stdin=Pipe()
        task.executableURL=URL(fileURLWithPath:executable); task.arguments=bundledEngine == nil ? ["-u","-m","koala.desktop"] : []
        if bundledEngine != nil {
            do { try FileManager.default.createDirectory(atPath:root,withIntermediateDirectories:true) }
            catch { self.error="Cannot create KOALA’s project directory: "+error.localizedDescription;return }
        }
        task.currentDirectoryURL=URL(fileURLWithPath:root)
        var environment=ProcessInfo.processInfo.environment
        if bundledEngine == nil { environment["PYTHONPATH"]=root+"/src" }
        else { environment.removeValue(forKey:"PYTHONPATH");environment.removeValue(forKey:"PYTHONHOME") }
        environment["PYTHONDONTWRITEBYTECODE"]="1"
        if !openAIKey.isEmpty { environment["OPENAI_API_KEY"]=openAIKey }
        if !arcKey.isEmpty { environment["ARC_API_KEY"]=arcKey }
        task.environment=environment; task.standardOutput=out; task.standardError=out; task.standardInput=stdin
        do { try task.run() } catch { self.error=error.localizedDescription; return }
        process=task; busy=true; stopping=false; log("Starting \(action.replacingOccurrences(of:"_",with:" "))…")
        // Pipe IO and model requests never block the native UI thread.
        DispatchQueue.global(qos:.userInitiated).async {
            stdin.fileHandleForWriting.write(input); try? stdin.fileHandleForWriting.close()
            var buffer=Data(), result: [String:Any]?, failure: String?, cancelled=false
            while true {
                let data=out.fileHandleForReading.availableData
                if data.isEmpty { break }; buffer.append(data)
                while let newline=buffer.firstIndex(of:10) {
                    let line=buffer.prefix(upTo:newline); buffer.removeSubrange(...newline)
                    if let event=(try? JSONSerialization.jsonObject(with:line)) as? [String:Any] {
                        switch event["event"] as? String {
                        case "progress": let message=event["message"] as? String ?? ""; DispatchQueue.main.async { self.log(message) }
                        case "result": result=event["data"] as? [String:Any]
                        case "error": failure=event["message"] as? String; cancelled=event["cancelled"] as? Bool ?? false
                        default: break
                        }
                    } else if let message=String(data:line,encoding:.utf8), !message.isEmpty { DispatchQueue.main.async { self.log(message) } }
                }
            }
            task.waitUntilExit()
            let finalResult=result, finalFailure=failure, wasCancelled=cancelled, code=task.terminationStatus
            DispatchQueue.main.async {
                self.busy=false; self.stopping=false; self.process=nil
                if let data=finalResult {
                    self.apply(data)
                    if let notice=data["research_confirmation"] as? [String:Any], let token=notice["token"] as? String {
                        self.log("Generation is waiting for your authorization.")
                        let alert=NSAlert(); alert.alertStyle = .warning
                        alert.messageText="Generate with incomplete research?"
                        alert.informativeText=notice["message"] as? String ?? "The source or author minimum has not been met."
                        alert.addButton(withTitle:"Cancel"); alert.addButton(withTitle:"Generate Anyway")
                        if alert.runModal() == .alertSecondButtonReturn {
                            var approved=extra; approved["research_approval"]=token
                            self.inference("generate",extra:approved)
                        }
                    } else { completion?(data); self.log("Finished.") }
                }
                else {
                    let message=finalFailure ?? "The operation stopped (exit \(code)). Saved checkpoints are retained."
                    self.log(message)
                    if !wasCancelled { self.error=message }
                    if !self.folder.isEmpty && action != "load" && action != "models" && action != "reuse_list" {
                        let savedBrief=self.brief, savedFields=self.fieldDrafts, savedAbstract=self.abstractText, dirtyBrief=self.briefDirty, dirtyAbstract=self.abstractDirty
                        self.run("load") { _ in
                            if dirtyBrief { self.brief=savedBrief; self.fieldDrafts=savedFields; self.briefDirty=true }
                            if dirtyAbstract { self.abstractText=savedAbstract; self.abstractDirty=true }
                        }
                    }
                }
            }
        }
    }
}

struct Panel<Content: View>: View {
    let title: String; let subtitle: String; @ViewBuilder var content: Content
    var body: some View { VStack(alignment:.leading,spacing:18) {
        VStack(alignment:.leading,spacing:5) { Text(title).font(.largeTitle.bold()); Text(subtitle).foregroundStyle(.secondary) }
        content
    }.padding(28).frame(maxWidth:.infinity,alignment:.leading) }
}
struct FieldEditor: View {
    let label: String; let hint: String; @Binding var text: String; var height: CGFloat=84
    var body: some View { VStack(alignment:.leading,spacing:5) {
        Text(label).font(.headline)
        if !hint.isEmpty { Text(hint).font(.caption).foregroundStyle(.secondary) }
        TextEditor(text:$text).font(.body).frame(height:height).padding(5).background(Color(nsColor:.textBackgroundColor)).clipShape(RoundedRectangle(cornerRadius:7)).overlay(RoundedRectangle(cornerRadius:7).stroke(Color.gray.opacity(0.25)))
    } }
}
struct RootView: View {
    @EnvironmentObject var studio: Studio
    @State var showLog=true
    var body: some View {
        NavigationSplitView {
            VStack(alignment:.leading,spacing:12) {
                HStack(spacing:10) { Image(nsImage:NSImage(contentsOfFile:(Bundle.main.resourcePath ?? studio.root)+"/koala-logo.png") ?? NSImage()).resizable().scaledToFit().frame(width:48,height:48).clipShape(RoundedRectangle(cornerRadius:9)); VStack(alignment:.leading) { Text("KOALA").font(.title2.bold()); Text("Writing studio").font(.caption).foregroundStyle(.secondary) } }.padding(.horizontal,14).padding(.top,14)
                HStack { Button { if studio.mayLeave() { studio.newProject=true } } label:{ Label("New",systemImage:"plus") }; Button { studio.openProject() } label:{ Label("Open",systemImage:"folder") } }.padding(.horizontal,14).disabled(studio.busy)
                Divider()
                List(selection:$studio.page) {
                    Section("Workspace") { ForEach(Array(pages.enumerated()),id:\.element) { index,page in Label(page == "Generate" ? "Ideas" : page,systemImage:symbols[index]).tag(page) } }
                    if !studio.recent.isEmpty { Section("Recent projects") { ForEach(studio.recent,id:\.self) { path in Button { studio.openRecent(path) } label:{ Label(studio.projectName(path),systemImage:"folder").lineLimit(1) }.buttonStyle(.plain).disabled(studio.busy).help(path) } } }
                }.listStyle(.sidebar)
                VStack(alignment:.leading,spacing:4) { Text("Knowledge-Oriented Australian Literary Analysis").font(.caption2).foregroundStyle(.secondary); Text("Version 0.22.0 · Native macOS").font(.caption2).foregroundStyle(.tertiary) }.padding(14)
            }.navigationSplitViewColumnWidth(min:210,ideal:235,max:300)
        } detail: {
            VStack(spacing:0) {
                HStack { VStack(alignment:.leading) { Text(studio.folder.isEmpty ? "Your next manuscript starts here" : studio.projectName(studio.folder)).font(.headline); if !studio.folder.isEmpty { Text(studio.folder).font(.caption).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle) } }; Spacer(); if !studio.folder.isEmpty { Button { NSWorkspace.shared.open(URL(fileURLWithPath:studio.folder)) } label:{ Image(systemName:"folder") }.help("Show project in Finder") }; Button { showLog.toggle() } label:{ Image(systemName:"list.bullet.rectangle") }.help("Show or hide activity") }.padding(16)
                Divider()
                ScrollView { Group {
                    if studio.folder.isEmpty && studio.page != "Settings" { WelcomeView() }
                    else { switch studio.page {
                    case "Generate": GenerateView()
                    case "Style": StyleView()
                    case "Prompts": PromptsView()
                    case "Brief": BriefView()
                    case "Outline": OutlineView()
                    case "Bibliography": BibliographyView()
                    case "Data": DataWorkspaceView()
                    case "Rewrite": RewriteView()
                    case "Repair": RepairView()
                    case "Inspiration": InspirationView()
                    case "Abstract": AbstractView()
                    case "Manuscript": ManuscriptView()
                    case "Export": ExportView()
                    case "Settings": SettingsView()
                    default: OverviewView()
                    } }
                }.frame(maxWidth:1000,alignment:.leading).frame(maxWidth:.infinity) }.background(Color(nsColor:.windowBackgroundColor))
                Divider()
                HStack { if studio.busy { ProgressView().controlSize(.small) }; Text(studio.lastMessage).font(.caption).lineLimit(2); Spacer(); if studio.busy { Button(studio.stopping ? "Stopping…" : "Stop",role:.cancel) { studio.stop() }.disabled(studio.stopping) } }.padding(12)
                if showLog { ScrollViewReader { proxy in ScrollView { Text(studio.activity.joined(separator:"\n")).font(.system(size:11,design:.monospaced)).textSelection(.enabled).frame(maxWidth:.infinity,alignment:.leading).padding(12); Color.clear.frame(height:1).id("end") }.frame(height:125).background(Color(nsColor:.textBackgroundColor)).onChange(of:studio.activity.count) { _ in proxy.scrollTo("end",anchor:.bottom) } } }
            }
        }.tint(accent).frame(minWidth:950,minHeight:700)
        .sheet(isPresented:$studio.newProject) { NewProjectView() }
        .sheet(isPresented:$studio.showRenameProject) { RenameProjectView() }
        .sheet(isPresented:$studio.showBibliography) { BibliographyImportView() }
        .sheet(isPresented:$studio.showReuse) { ReuseView() }
        .alert("KOALA",isPresented:Binding(get:{studio.error != nil},set:{if !$0 { studio.error=nil }})) { Button("OK") { studio.error=nil } } message:{ Text(studio.error ?? "") }
    }
}
struct WelcomeView: View {
    @EnvironmentObject var studio: Studio
    var body: some View { Panel(title:"Ideas into scholarly writing",subtitle:"Develop an article or a book, one considered step at a time.") {
        HStack(spacing:16) {
            welcomeCard("Article","A focused scholarly argument, guided by a 250–300-word abstract.","doc.text")
            welcomeCard("Book","40,000–100,000 words, with chapters, an introduction, and optional appendices.","books.vertical")
        }
        HStack { Button("Create a project") { studio.newProject=true }.buttonStyle(.borderedProminent); Button("Open existing project") { studio.openProject() } }.disabled(studio.busy)
        Text("Bring DOCX, RTF, TXT, HTML or PDF inspiration, specify authors and ideas, or leave the subject open.").foregroundStyle(.secondary).padding(.top,12)
    } }
    func welcomeCard(_ title:String,_ text:String,_ icon:String)->some View { VStack(alignment:.leading,spacing:12) { Image(systemName:icon).font(.largeTitle).foregroundStyle(accent); Text(title).font(.title2.bold()); Text(text).foregroundStyle(.secondary).frame(maxWidth:.infinity,alignment:.leading) }.padding(22).frame(maxWidth:.infinity,minHeight:180,alignment:.topLeading).background(.background,in:RoundedRectangle(cornerRadius:14)) }
}
struct OverviewView: View {
    @EnvironmentObject var studio: Studio
    var body: some View { Panel(title:studio.isBook ? "Your book" : "Your article",subtitle:studio.brief["topic"] as? String ?? "") {
        Button("Rename project…") { if studio.requireSaved() { studio.showRenameProject=true } }.disabled(studio.busy)
        HStack(spacing:24) { metric("Target words",studio.value("target_words")); metric("Sections saved","\(studio.sections.count)"); metric("Inspiration","\(studio.documents.count) documents"); metric("Sources","\((studio.article["sources"] as? [Any] ?? []).count)") }
        let next=studio.project["next"] as? [String] ?? ["Create guiding abstract","abstract"]
        GroupBox { VStack(alignment:.leading,spacing:12) { Text("Next step").font(.headline); Text(next[0]).font(.title2); HStack { Button("Continue") { if next[1] == "repair-citations" { studio.page="Repair" } else if next[1] == "review" { studio.page="Manuscript" } else { studio.page=next[1] == "abstract" ? "Abstract" : "Manuscript"; studio.inference(next[1]) } }.buttonStyle(.borderedProminent).disabled(studio.busy || studio.dirty); Button("Edit brief") { studio.page="Brief" } }; if studio.dirty { Text("Save your brief or abstract edits before continuing.").foregroundStyle(.orange) } }.padding(12).frame(maxWidth:.infinity,alignment:.leading) }
        Button("Develop ideas, authors, and a plan…") { studio.page="Generate" }
        Text("Brief  →  Generate  →  Abstract  →  Manuscript  →  Export").font(.headline).foregroundStyle(accent)
        Text("Saved work stays in your project folder. Revisions preserve earlier prose and exports.").foregroundStyle(.secondary)
        if let report=studio.project["audit"] as? [String:Any], let issues=report["issues"] as? [String], !issues.isEmpty { GroupBox("Review notes") { VStack(alignment:.leading,spacing:6) { ForEach(issues,id:\.self) { Text("• "+$0).font(.callout) } }.frame(maxWidth:.infinity,alignment:.leading).padding(8) } }
    } }
    func metric(_ label:String,_ value:String)->some View { VStack(alignment:.leading,spacing:5) { Text(value).font(.title2.bold()); Text(label).font(.caption).foregroundStyle(.secondary) }.frame(maxWidth:.infinity,alignment:.leading) }
}
struct BriefView: View {
    @EnvironmentObject var studio: Studio
    let fields:[(String,String,Bool)] = [("topic","Subject / topic",false),("discipline","Discipline",false),("target_journals","Target journals",true),("target_publishers","Publishers or series",true),("similar_articles","Comparable articles",true),("similar_books","Comparable books",true),("important_authors","Required authors — each must be cited",true),("important_ideas","Important ideas and themes",true),("possible_citations","Possible citations or DOIs",true),("research_guidance","Research guidance",false),("style_guidance","Writing style",false),("appendices","Appendix titles",true),("source_files","Source file paths",true),("inspiration_files","Inspiration file paths",true),("sources_file","Curated source ledger path",false)]
    var body: some View { Panel(title:"Shape the brief",subtitle:"Leave optional fields blank to let KOALA propose a direction. Citation-only changes retain prose; other brief changes archive and restart the draft.") {
        TextField("Manuscript title (optional)",text:studio.binding("manuscript_title")).textFieldStyle(.roundedBorder)
        Button("Generate title options…") { studio.generationKind="titles";studio.refreshProposal();studio.page="Generate" }
        HStack { TextField("Target words",text:studio.binding("target_words",number:true)); TextField("Cited works (blank = automatic)",text:studio.binding("citation_target",number:true)); if studio.isBook { TextField("Main chapters",text:studio.binding("chapter_count",number:true)) } }.textFieldStyle(.roundedBorder)
        Picker("Citation style",selection:studio.binding("citation_style")) { Text("MLA").tag("mla"); Text("Chicago author–date").tag("chicago-author-date"); Text("Legacy author–date").tag("author-date"); Text("Numeric").tag("numeric") }.pickerStyle(.segmented)
        if studio.isBook { Toggle("Include an afterword",isOn:Binding(get:{studio.brief["include_afterword"] as? Bool ?? false},set:{studio.brief["include_afterword"]=$0;studio.briefDirty=true})) }
        if studio.isBook { Button("Open chapter outline…") { studio.page="Outline" } }
        ForEach(fields.filter { studio.isBook || !["target_publishers","similar_books","appendices"].contains($0.0) },id:\.0) { key,label,list in
            FieldEditor(label:label,hint:key == "important_authors" ? "Up to 999 names. \((studio.brief[key] as? [String] ?? []).count) entered." : (list ? "One entry per line or separate entries with semicolons." : ""),text:studio.binding(key,list:list),height:key == "important_authors" ? 130 : 65)
            if key == "important_authors" { Button("Import author list…") { studio.chooseAuthors() } }
        }
        HStack { Button("Save brief") { studio.run("save_brief",extra:["brief":studio.brief]) }.buttonStyle(.borderedProminent).disabled(!studio.briefDirty); Text(studio.briefDirty ? "Unsaved changes" : "All changes saved").foregroundStyle(.secondary) }
    }.disabled(studio.busy || studio.abstractDirty) }
}
struct OutlineView: View {
    @EnvironmentObject var studio: Studio
    var body: some View { Panel(title:"Chapter outline",subtitle:"Bring a table of contents and shape the structure before drafting.") {
        if !studio.isBook {
            Text("Chapter-outline imports are available in book projects. For an article, use the brief and inspiration documents to guide its structure.").foregroundStyle(.secondary)
            Button("Edit article brief") { studio.page="Brief" }
        } else {
            HStack {
                Button("Import outline…") { studio.chooseOutline() }.buttonStyle(.borderedProminent)
                Button("Clear outline") { studio.binding("chapter_outline").wrappedValue=""; if !(5...8).contains(Int(studio.value("chapter_count")) ?? 6) { studio.binding("chapter_count",number:true).wrappedValue="6" } }
                Spacer()
                Text("DOCX · PDF · TXT · Markdown").font(.caption).foregroundStyle(.secondary)
            }
            Text("Numbered chapter headings set the titles, order, and count, up to 30 main chapters. Unnumbered notes guide the selected chapter count. Import happens locally without an API key.").foregroundStyle(.secondary)
            FieldEditor(label:"Your outline",hint:"Review and edit the extracted text before saving. Scanned PDFs need OCR first.",text:studio.binding("chapter_outline"),height:350)
            HStack { TextField("Main chapters",text:studio.binding("chapter_count",number:true)).frame(width:170).textFieldStyle(.roundedBorder); Spacer(); Button("Save outline and brief") { studio.run("save_brief",extra:["brief":studio.brief]) }.buttonStyle(.borderedProminent).disabled(!studio.briefDirty) }
            if !studio.sections.isEmpty || !studio.abstractText.isEmpty { Label("Saving a changed outline archives the current manuscript and restarts planning, including the guiding abstract.",systemImage:"clock.arrow.circlepath").font(.callout).foregroundStyle(.secondary) }
            if studio.briefDirty { Text("Unsaved brief and outline changes will be saved together.").font(.caption).foregroundStyle(.orange) }
        }
    }.disabled(studio.busy || studio.abstractDirty) }
}
struct RepairView: View {
    @EnvironmentObject var studio: Studio
    @State var search=""
    @State var onlyMissing=true
    var readiness:[String:Any] { studio.project["citation_readiness"] as? [String:Any] ?? [:] }
    var report:[String:Any] { studio.project["audit"] as? [String:Any] ?? [:] }
    var authors:[[String:Any]] { readiness["authors"] as? [[String:Any]] ?? [] }
    var repair:[String:Any] { studio.article["citation_repair"] as? [String:Any] ?? [:] }
    var proseRepair:[String:Any] { studio.article["manuscript_repair"] as? [String:Any] ?? [:] }
    var repairComplete:Bool { proseRepair["complete"] as? Bool ?? false }
    var sameInstructions:Bool { (proseRepair["instructions"] as? String ?? "") == studio.manuscriptRepairInstructions.trimmingCharacters(in:.whitespacesAndNewlines) }
    var cited:Int { report["distinct_cited_works"] as? Int ?? 0 }
    var target:Int { readiness["target"] as? Int ?? 0 }
    var covered:Int { authors.filter { $0["status"] as? String == "cited" }.count }
    var filtered:[[String:Any]] { authors.filter { row in
        (!onlyMissing || row["status"] as? String != "cited") && (search.isEmpty || (row["author"] as? String ?? "").localizedCaseInsensitiveContains(search))
    } }
    var body: some View { Panel(title:"Repair manuscript",subtitle:"Fix recurring prose problems across drafted sections while preserving the argument and most of the wording.") {
        GroupBox("Global prose repair") {
            VStack(alignment:.leading,spacing:12) {
                FieldEditor(label:"What should be fixed throughout the manuscript?",hint:"Describe a specific problem. KOALA applies small edits to existing sections and preserves citations and quotations.",text:$studio.manuscriptRepairInstructions,height:140).disabled(studio.busy)
                HStack {
                    Button("Fix abstract / record wording") { studio.manuscriptRepairInstructions=studio.project["default_manuscript_repair"] as? String ?? "" }.disabled(studio.busy)
                    Spacer()
                    Button(repairComplete || !sameInstructions ? "Start repair pass" : (proseRepair.isEmpty ? "Repair manuscript" : "Resume manuscript repair")) {
                        studio.inference("repair-manuscript",extra:["repair_instructions":studio.manuscriptRepairInstructions,"restart_repair":repairComplete])
                    }.buttonStyle(.borderedProminent).disabled(studio.busy || studio.dirty || studio.sections.isEmpty || studio.manuscriptRepairInstructions.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty)
                }
                Text("Each pass saves an original backup and a before-and-after report. Broad or unsafe edits are skipped for review; the original section is retained. Uses your selected model and API key. Stop and resume from the saved checkpoint; re-export when finished.").font(.callout).foregroundStyle(.secondary)
                if let processed=proseRepair["processed"] as? Int {
                    Text("\(processed) of \(proseRepair["total"] as? Int ?? 0) sections reviewed · \(proseRepair["changed"] as? Int ?? 0) changed · \(proseRepair["needs_review"] as? Int ?? 0) need review").font(.callout)
                    if repairComplete { Text("Repair pass complete. Review the changes, then export the updated manuscript.").foregroundStyle(accent) }
                    HStack {
                        if let path=proseRepair["report"] as? String { Button("Review changes") { NSWorkspace.shared.open(URL(fileURLWithPath:path)) } }
                        if let path=proseRepair["archive"] as? String { Button("Show original backup") { NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath:path)]) } }
                        if !repairComplete {
                            Button("Start a new pass") { studio.inference("repair-manuscript",extra:["repair_instructions":studio.manuscriptRepairInstructions,"restart_repair":true]) }.disabled(studio.busy || studio.dirty || studio.manuscriptRepairInstructions.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty)
                        }
                        Button("Go to export") { studio.page="Export" }.disabled(studio.busy)
                    }
                }
            }.padding(8)
        }
        Divider()
        Text("Citation repair").font(.title2.bold())
        HStack(spacing:20) {
            metric("Distinct works cited","\(cited) / \(target)")
            metric("Required authors cited","\(covered) / \(authors.count)")
            metric("Works with evidence","\((readiness["supported_source_ids"] as? [String] ?? []).count)")
        }
        ProgressView(value:Double(min(cited,target)),total:Double(max(1,target))).tint(accent)
        if let processed=repair["processed"] as? Int { Text("Repair checkpoint: \(processed) of \(studio.sections.count) sections reviewed.").font(.callout) }
        HStack {
            Button(repair.isEmpty ? "Start citation repair" : "Resume citation repair") { studio.inference("repair-citations") }.buttonStyle(.borderedProminent).disabled(studio.busy || studio.dirty || studio.sections.isEmpty)
            Button("Edit authors and target") { studio.page="Brief" }
            Button("Refresh coverage") { if studio.requireSaved() { studio.run("load") } }.disabled(studio.busy || studio.dirty)
        }
        if studio.sections.isEmpty { Text("Generate manuscript sections before using repair.").foregroundStyle(.secondary) }
        if studio.dirty { Text("Save your brief or abstract edits before starting repair.").foregroundStyle(.orange) }
        Text("Repair uses your selected provider and API key. You can stop from the activity bar and resume here. Missing source evidence may pause the operation before prose changes.").font(.callout).foregroundStyle(.secondary)
        GroupBox("Source evidence") {
            VStack(alignment:.leading,spacing:10) {
                Text("Add accurate abstracts, research notes, or passages to the project’s source ledger when evidence is missing. A bibliography record alone does not support a claim.")
                HStack {
                    Button("Open source ledger") { NSWorkspace.shared.open(URL(fileURLWithPath:studio.folder+"/sources.json")) }.disabled(!FileManager.default.fileExists(atPath:studio.folder+"/sources.json"))
                    Button("Show project folder") { NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath:studio.folder)]) }
                    if let archive=repair["archive"] as? String { Button("Show original manuscript") { NSWorkspace.shared.open(URL(fileURLWithPath:archive)) } }
                }
            }.padding(8).frame(maxWidth:.infinity,alignment:.leading)
        }
        HStack { Text("Required authors").font(.headline); Spacer(); Toggle("Show missing only",isOn:$onlyMissing).toggleStyle(.checkbox) }
        TextField("Find an author",text:$search).textFieldStyle(.roundedBorder)
        if authors.isEmpty { Text("Add required authors in Brief to track their citation coverage.").foregroundStyle(.secondary) }
        else if filtered.isEmpty { Text(search.isEmpty ? "All required authors have an in-text citation." : "No authors match this filter.").foregroundStyle(.secondary) }
        LazyVStack(alignment:.leading,spacing:0) {
            ForEach(Array(filtered.enumerated()),id:\.offset) { _,row in
                HStack { VStack(alignment:.leading) { Text(row["author"] as? String ?? ""); if let ids=row["secondary_ids"] as? [String], !ids.isEmpty { Text("Secondary sources: "+ids.joined(separator:", ")).font(.caption).foregroundStyle(.secondary) } }; Spacer(); Text(status(row["status"] as? String ?? "")).font(.callout).foregroundStyle(row["status"] as? String == "cited" ? Color.green : Color.orange) }.padding(.vertical,9)
                Divider()
            }
        }.textSelection(.enabled)
    } }
    func metric(_ label:String,_ value:String)->some View { VStack(alignment:.leading,spacing:5) { Text(value).font(.title2.bold()); Text(label).font(.caption).foregroundStyle(.secondary) }.frame(maxWidth:.infinity,alignment:.leading) }
    func status(_ value:String)->String {
        switch value { case "cited": return "Cited"; case "not_cited": return "Ready to cite"; case "missing_evidence": return "Needs source evidence"; default: return "Needs a matching work" }
    }
}
struct InspirationView: View {
    @EnvironmentObject var studio: Studio
    var body: some View { Panel(title:"Bring your reading",subtitle:"Analyze DOCX, RTF, TXT, HTML or text-based PDF files, or reuse completed analysis from another project.") {
        HStack { Button { studio.addDocuments() } label:{ Label("Add documents…",systemImage:"plus") }.buttonStyle(.borderedProminent); Button { studio.chooseReuse() } label:{ Label("Reuse analysis…",systemImage:"arrow.triangle.branch") } }.disabled(studio.busy)
        Label("You can start generating text after inspiration analysis is complete. Create guiding abstract, Continue, and Edit brief are temporarily unavailable while analysis is running.", systemImage: "info.circle").font(.callout).foregroundStyle(.secondary)
        Text("New documents are analyzed once per chunk. HTML scripts, styles, markup, and code blocks are stripped; RTF is converted to plain text. Scanned PDFs need OCR first. Importing into a started project archives its draft before replanning.").font(.callout).foregroundStyle(.secondary)
        if studio.documents.isEmpty { Text("No inspiration documents attached yet.").padding(.vertical,22).foregroundStyle(.secondary) }
        ForEach(Array(studio.documents.enumerated()),id:\.offset) { _,doc in GroupBox {
            VStack(alignment:.leading,spacing:6) { Label(doc["name"] as? String ?? "Document",systemImage:"doc.text").font(.headline); Text("\(doc["chunk_count"] as? Int ?? 0) chunks · \(doc["model"] as? String ?? "")").font(.caption).foregroundStyle(.secondary); if let digest=doc["digest"] as? [String:Any] { Text(digest["overview"] as? String ?? "").textSelection(.enabled) }; if let warnings=doc["warnings"] as? [String], !warnings.isEmpty { Text("\(warnings.count) extraction/analysis notes in the saved report").font(.caption).foregroundStyle(.orange) } }.frame(maxWidth:.infinity,alignment:.leading).padding(8)
        } }
        if let digest=(studio.article["inspiration"] as? [String:Any])?["digest"] as? [String:Any] {
            ForEach(["themes","ideas","authors","citations","research_questions","style_notes"],id:\.self) { key in
                let items=digest[key] as? [[String:Any]] ?? []
                if !items.isEmpty { DisclosureGroup(key.replacingOccurrences(of:"_",with:" ").capitalized) { VStack(alignment:.leading,spacing:8) { ForEach(Array(items.enumerated()),id:\.offset) { _,item in Text("• "+(item["text"] as? String ?? "")).textSelection(.enabled) } }.frame(maxWidth:.infinity,alignment:.leading).padding(.top,8) } }
            }
        }
    } }
}
struct AbstractView: View {
    @EnvironmentObject var studio: Studio
    var body: some View { Panel(title:"The guiding abstract",subtitle:"A 250–300-word proposal that guides the argument and structure of your manuscript.") {
        Button(studio.abstractText.isEmpty ? "Create abstract" : "Resume abstract stage") { studio.inference("abstract") }.buttonStyle(.borderedProminent).disabled(studio.busy || studio.dirty)
        FieldEditor(label:"Abstract",hint:"Edit the text below, then save. Saving archives the previous draft and prepares it for redrafting.",text:Binding(get:{studio.abstractText},set:{studio.abstractText=$0;studio.abstractDirty=true}),height:340).disabled(studio.busy || studio.briefDirty)
        HStack { Text("\(studio.abstractText.split(whereSeparator: { $0.isWhitespace }).count) words (approximate)").foregroundStyle(.secondary); Spacer(); Button("Save edited abstract") { studio.run("save_abstract",extra:["text":studio.abstractText]) }.disabled(studio.busy || !studio.abstractDirty || studio.article["abstract"] == nil) }
    } }
}
struct ManuscriptView: View {
    @EnvironmentObject var studio: Studio
    @State var sectionIndex=0
    @State var tab="Draft"
    var body: some View { Panel(title:"Build the manuscript",subtitle:"Completed sections are saved as the work progresses. Stop and resume without starting over.") {
        HStack { Button(studio.sections.isEmpty ? "Generate manuscript" : "Resume manuscript") { studio.inference("generate") }.buttonStyle(.borderedProminent).disabled(studio.busy || studio.dirty); Button("Repair manuscript…") { studio.page="Repair" }.disabled(studio.busy || studio.dirty || studio.sections.isEmpty); Text("\(studio.sections.count) sections saved").foregroundStyle(.secondary) }
        Picker("View",selection:$tab) { Text("Draft").tag("Draft"); Text("Outline").tag("Outline"); Text("Sources").tag("Sources"); Text("Audit").tag("Audit") }.pickerStyle(.segmented)
        if tab == "Draft" {
            if let issue=studio.project["citation_preview_error"] as? String, !issue.isEmpty { Text("Citation preview: "+issue).foregroundStyle(.orange) }
            if studio.sections.isEmpty { Text("Your drafted sections will appear here.").foregroundStyle(.secondary).padding(.vertical,24) }
            else {
                Picker("Section",selection:$sectionIndex) { ForEach(Array(studio.sections.enumerated()),id:\.offset) { i,item in Text(item["heading"] as? String ?? "Section \(i+1)").tag(i) } }
                Text((studio.project["formatted_sections"] as? [String]).flatMap { $0.indices.contains(sectionIndex) ? $0[sectionIndex] : nil } ?? (studio.sections[min(sectionIndex,studio.sections.count-1)]["text"] as? String ?? "")).font(.system(size:16,design:.serif)).lineSpacing(6).textSelection(.enabled).frame(maxWidth:.infinity,alignment:.leading).padding(22).background(.background,in:RoundedRectangle(cornerRadius:10))
            }
        } else if tab == "Outline" {
            let plan=studio.article["plan"] as? [String:Any] ?? [:]
            ForEach(Array((plan["sections"] as? [[String:Any]] ?? []).enumerated()),id:\.offset) { i,item in VStack(alignment:.leading,spacing:5) { Text("\(i+1). "+(item["heading"] as? String ?? "")).font(.headline); Text(item["purpose"] as? String ?? "").foregroundStyle(.secondary) }.frame(maxWidth:.infinity,alignment:.leading) }
        } else if tab == "Sources" {
            if let readiness = studio.project["citation_readiness"] as? [String:Any] {
                Text("\((readiness["supported_source_ids"] as? [String] ?? []).count) works with evidence · target \(readiness["target"] as? Int ?? 0)").font(.headline)
                Text("Add missing abstracts, research notes, or located passages to sources.json in the project folder, then choose Repair citations. Metadata alone does not support claims.").foregroundStyle(.secondary)
                Button("Open source ledger") { NSWorkspace.shared.open(URL(fileURLWithPath:studio.folder+"/sources.json")) }
            }
            ForEach(Array((studio.article["sources"] as? [[String:Any]] ?? []).enumerated()),id:\.offset) { _,item in VStack(alignment:.leading,spacing:5) { Text((item["id"] as? String ?? "")+" · "+(item["title"] as? String ?? "")).font(.headline); Text((item["authors"] as? [String] ?? []).joined(separator:", ")).foregroundStyle(.secondary); Text(item["verification"] as? String ?? "Unverified").font(.caption) }.textSelection(.enabled).frame(maxWidth:.infinity,alignment:.leading) }
        } else {
            if let report=studio.project["audit"] as? [String:Any] {
                Text("Body: \(report["body_words"] as? Int ?? 0) words · \(report["distinct_cited_works"] as? Int ?? 0) distinct cited works").font(.headline)
                let issues=report["issues"] as? [String] ?? []
                if issues.isEmpty { Label("Automated checks passed",systemImage:"checkmark.circle").foregroundStyle(.green) }
                ForEach(issues,id:\.self) { Text("• "+$0) }
                if let authors = report["author_coverage"] as? [[String:Any]], !authors.isEmpty {
                    Text("Required author coverage").font(.headline)
                    ForEach(Array(authors.enumerated()),id:\.offset) { _,row in
                        HStack { Text(row["author"] as? String ?? ""); Spacer(); Text((row["status"] as? String ?? "").replacingOccurrences(of:"_",with:" ")).foregroundStyle(row["status"] as? String == "cited" ? Color.green : Color.orange) }
                    }
                }
                Text(report["note"] as? String ?? "Review source relevance and factual claims before publication.").foregroundStyle(.secondary)
            } else { Text("Draft some sections to see the citation and length audit.").foregroundStyle(.secondary) }
        }
    } }
}
struct ExportView: View {
    @EnvironmentObject var studio: Studio
    @State var formats:Set<String>=["docx","pdf"]
    @State var abstractOnly=false
    @State var strict=false
    var body: some View { Panel(title:"Export your work",subtitle:"Create documents for review, sharing, and revision.") {
        HStack(spacing:22) { ForEach(["docx","pdf","html","txt","rtf"],id:\.self) { format in Toggle(format.uppercased(),isOn:Binding(get:{formats.contains(format)},set:{if $0 { formats.insert(format) } else { formats.remove(format) }})) } }
        Toggle("Export the abstract only",isOn:$abstractOnly)
        Toggle("Require all manuscript audit checks to pass",isOn:$strict).disabled(abstractOnly)
        Button("Export selected formats") { if studio.requireSaved() { studio.run("export",extra:["formats":formats.sorted(),"abstract_only":abstractOnly,"strict":strict && !abstractOnly]) } }.buttonStyle(.borderedProminent).disabled(studio.busy || formats.isEmpty || studio.article.isEmpty)
        Text("Every export includes an AI-assistance disclosure. Files are saved in the project folder.").foregroundStyle(.secondary)
        ForEach(studio.project["exports"] as? [String] ?? [],id:\.self) { path in HStack { Label(URL(fileURLWithPath:path).lastPathComponent,systemImage:"doc"); Spacer(); Button("Open") { NSWorkspace.shared.open(URL(fileURLWithPath:path)) }; Button("Show in Finder") { NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath:path)]) } }.padding(10).background(.background,in:RoundedRectangle(cornerRadius:8)) }
    } }
}
struct SettingsView: View {
    @EnvironmentObject var studio: Studio
    var body: some View { Panel(title:"Inference settings",subtitle:"Choose the service and model that will help develop your manuscript.") {
        Picker("Provider",selection:Binding(get:{studio.provider},set:{ value in studio.provider=value; studio.model=value == "openai" ? "gpt-6-luna" : "gpt-oss-120b"; studio.endpoint=""; studio.models=[] })) { Text("OpenAI").tag("openai"); Text("Virginia Tech ARC").tag("arc") }.pickerStyle(.segmented)
        SecureField("API key",text:studio.activeKey).textFieldStyle(.roundedBorder)
        Text("Keys stay in memory for this app session. They are never saved in the project or app preferences.").font(.caption).foregroundStyle(.secondary)
        TextField("Model ID",text:$studio.model).textFieldStyle(.roundedBorder)
        HStack { Button("Fetch available models") { studio.run("models") { data in studio.models=data["models"] as? [String] ?? [] } }; TextField("Filter models",text:$studio.modelFilter).textFieldStyle(.roundedBorder) }
        if !studio.models.isEmpty { ScrollView { LazyVStack(alignment:.leading) { ForEach(studio.models.filter { studio.modelFilter.isEmpty || $0.localizedCaseInsensitiveContains(studio.modelFilter) },id:\.self) { model in Button { studio.model=model } label:{ HStack { Text(model); Spacer(); if model==studio.model { Image(systemName:"checkmark") } }.padding(5) }.buttonStyle(.plain) } } }.frame(height:180).padding(8).background(.background,in:RoundedRectangle(cornerRadius:8)) }
        TextField("Custom HTTPS API endpoint (optional)",text:$studio.endpoint).textFieldStyle(.roundedBorder)
        if !studio.folder.isEmpty { Button("Save project settings") { if studio.requireSaved() { studio.run("settings",extra:["settings":studio.settings]) } }.buttonStyle(.borderedProminent) }
        Divider()
        if studio.bundledEngine != nil { Text("Standalone app — Python and document tools are bundled.").font(.callout) }
        else {
        Text("KOALA engine folder").font(.headline); Text(studio.root).font(.caption).textSelection(.enabled)
        Button("Locate KOALA folder…") { if let url=studio.directory(prompt:"Use KOALA Folder") { studio.root=url.path; UserDefaults.standard.set(url.path,forKey:"engineRoot") } }
        }
    }.disabled(studio.busy) }
}
struct NewProjectView: View {
    @EnvironmentObject var studio: Studio
    @Environment(\.dismiss) var dismiss
    @State var kind="article"
    @State var name=""
    @State var parent=""
    @State var topic=""
    @State var target=6500
    @State var chapters=6
    @State var afterword=false
    @State var appendices=""
    var body: some View { VStack(alignment:.leading,spacing:18) {
        Text("Create a project").font(.title.bold())
        if let message=studio.error { Text(message).font(.callout).foregroundStyle(.red) }
        Picker("Type",selection:$kind) { Text("Article").tag("article"); Text("Book").tag("book") }.pickerStyle(.segmented).onChange(of:kind) { value in target=value == "book" ? 65000 : 6500 }
        Text("Project name (required)").font(.headline)
        TextField("e.g. Nihilism and Modern Life",text:$name).textFieldStyle(.roundedBorder)
        Text("This names your project and its new folder. You can change the display name later from Overview.").font(.caption).foregroundStyle(.secondary)
        HStack { Text(parent).font(.caption).lineLimit(2); Spacer(); Button("Choose location…") { if let url=studio.directory(prompt:"Choose Location") { parent=url.path } } }
        TextField("Topic (optional)",text:$topic).textFieldStyle(.roundedBorder)
        HStack { Text("Target words"); TextField("Words",value:$target,formatter:NumberFormatter()).frame(width:140).textFieldStyle(.roundedBorder); Text(kind == "book" ? "40,000–100,000" : "1,000–20,000").foregroundStyle(.secondary) }
        if kind == "book" { Stepper("\(chapters) main chapters + introduction",value:$chapters,in:5...8); Toggle("Include afterword",isOn:$afterword); TextField("Appendix titles (separate with semicolons)",text:$appendices).textFieldStyle(.roundedBorder) }
        HStack { Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction); Spacer(); Button("Create project") {
            var brief:[String:Any]=["project_type":kind,"topic":topic,"target_words":target,"chapter_count":chapters,"include_afterword":afterword,"appendices":appendices.split(separator:";").map { $0.trimmingCharacters(in:.whitespaces) }]
            if kind == "book" { brief["citation_target"]=NSNull() }
            let folder=URL(fileURLWithPath:parent).appendingPathComponent(name.trimmingCharacters(in:.whitespacesAndNewlines)).path
            studio.run("create",extra:["folder":folder,"brief":brief,"name":name]) { _ in studio.page="Overview"; dismiss() }
        }.buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction).disabled(studio.busy || name.trimmingCharacters(in:.whitespaces).isEmpty || name.contains("/") || name.contains(":") || name.contains("\\") || name.count>120 || name=="." || name=="..") }
    }.padding(28).frame(width:550).onAppear { parent=studio.root+"/output" }.disabled(studio.busy) }
}
struct ReuseView: View {
    @EnvironmentObject var studio: Studio
    @Environment(\.dismiss) var dismiss
    var body: some View { VStack(alignment:.leading,spacing:16) {
        if let message=studio.error { Text(message).font(.callout).foregroundStyle(.red) }
        Text("Reuse completed analysis").font(.title.bold()); Text(studio.reuseSource).font(.caption).foregroundStyle(.secondary)
        Text("Copies the analysis and evidence into this project. No model calls or matching API key are needed.").foregroundStyle(.secondary)
        ScrollView { VStack(alignment:.leading,spacing:12) { ForEach(Array(studio.analyses.enumerated()),id:\.offset) { _,item in
            let path=item["path"] as? String ?? ""
            Toggle(isOn:Binding(get:{studio.selectedAnalyses.contains(path)},set:{ if $0 {studio.selectedAnalyses.insert(path)}else{studio.selectedAnalyses.remove(path)} })) { VStack(alignment:.leading) { Text(item["name"] as? String ?? "Document"); Text("\(item["chunks"] as? Int ?? 0) chunks · \(item["model"] as? String ?? "")").font(.caption).foregroundStyle(.secondary) } }
        } } }.frame(height:240)
        HStack { Button("Select all") { studio.selectedAnalyses=Set(studio.analyses.compactMap{$0["path"] as? String}) }; Spacer(); Button("Cancel") { dismiss() }; Button("Reuse selected") { studio.run("reuse",extra:["source":studio.reuseSource,"analyses":Array(studio.selectedAnalyses)]) { _ in dismiss() } }.buttonStyle(.borderedProminent).disabled(studio.selectedAnalyses.isEmpty) }
    }.padding(28).frame(width:620).disabled(studio.busy) }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    @MainActor var studio: Studio?
    func applicationShouldTerminate(_ sender:NSApplication)->NSApplication.TerminateReply {
        guard let studio else { return .terminateNow }
        if studio.busy {
            let alert=NSAlert();alert.messageText="Stop the current operation and quit?";alert.informativeText="Completed checkpoints are retained. The current unfinished request may be discarded.";alert.addButton(withTitle:"Keep Running");alert.addButton(withTitle:"Stop and Quit")
            if alert.runModal() != .alertSecondButtonReturn { return .terminateCancel }
            studio.stop()
        } else if !studio.mayLeave() { return .terminateCancel }
        return .terminateNow
    }
}
@main struct KOALAApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject var studio=Studio()
    var body: some Scene {
        Window("KOALA",id:"main") { RootView().environmentObject(studio).onAppear { delegate.studio=studio } }.defaultSize(width:1180,height:820)
        .commands {
            CommandGroup(replacing:.newItem) {
                Button("New Project…") { if studio.mayLeave() { studio.newProject=true } }.keyboardShortcut("n").disabled(studio.busy)
                Button("Open Project…") { studio.openProject() }.keyboardShortcut("o").disabled(studio.busy)
            }
            CommandMenu("Project") {
                Button("Show in Finder") { NSWorkspace.shared.open(URL(fileURLWithPath:studio.folder)) }.disabled(studio.folder.isEmpty)
                Button("Rename Project…") { if studio.requireSaved() { studio.showRenameProject=true } }.disabled(studio.busy || studio.folder.isEmpty)
                Button("Refresh") { if studio.mayLeave() { studio.run("load") } }.keyboardShortcut("r").disabled(studio.busy || studio.folder.isEmpty)
                Button("Stop Operation") { studio.stop() }.keyboardShortcut(".").disabled(!studio.busy)
                Divider()
                Button("Delete Project…",role:.destructive) { studio.deleteProject() }.disabled(studio.busy || studio.folder.isEmpty)
            }
        }
    }
}


struct BibliographyView: View {
    @EnvironmentObject var studio: Studio
    @State var search=""
    @State var tab="Sources"
    var bibliography:[String:Any] { studio.project["bibliography"] as? [String:Any] ?? [:] }
    var sources:[[String:Any]] { bibliography["sources"] as? [[String:Any]] ?? [] }
    var candidates:[String] { bibliography["candidates"] as? [String] ?? [] }
    var body: some View { Panel(title:"Bibliography",subtitle:"Bring an existing bibliography to guide the argument, research, and chapters of your manuscript.") {
        HStack {
            Button { studio.chooseBibliography() } label:{ Label("Import bibliography…",systemImage:"square.and.arrow.down") }.buttonStyle(.borderedProminent).disabled(studio.busy || studio.dirty)
            Button("Expand research") { if studio.requireSaved() { studio.run("expand_research") } }.disabled(studio.busy || studio.dirty || studio.article.isEmpty)
            Button("Edit reference candidates") { studio.page="Brief" }
            Spacer()
            Text("\(sources.count) sources · \(sources.filter { $0["cited"] as? Bool == true }.count) cited").foregroundStyle(.secondary)
        }
        Text("Expand research searches primary works through author-specific Crossref queries, Open Library editions, and Project Gutenberg texts, alongside secondary literature. It continues seeking primary works even when secondary coverage is complete. It preserves your abstract and manuscript, uses public metadata services without an LLM key, and marks secondary relationships separately. Review author identity and relevance before drafting.").font(.callout).foregroundStyle(.secondary)
        Text("Import DOCX, text-based PDF, TXT, or Markdown. Review locally before adding references; no API key is needed to import. Research candidates guide planning and discovery. They become usable citations only when matched to relevant sources with supporting evidence.").font(.callout).foregroundStyle(.secondary)
        Picker("Show",selection:$tab) { Text("Source ledger (\(sources.count))").tag("Sources"); Text("Research candidates (\(candidates.count))").tag("Candidates") }.pickerStyle(.segmented)
        TextField("Search titles, authors, years, or references",text:$search).textFieldStyle(.roundedBorder)
        if tab == "Sources" {
            if sources.isEmpty { Text("No source records yet. Import a bibliography, then create the abstract to begin research.").foregroundStyle(.secondary) }
            LazyVStack(alignment:.leading,spacing:12) {
                ForEach(Array(sources.filter { search.isEmpty || String(describing:$0).localizedCaseInsensitiveContains(search) }.enumerated()),id:\.offset) { _,source in
                    GroupBox {
                        VStack(alignment:.leading,spacing:6) {
                            HStack { Text(source["title"] as? String ?? "Untitled").font(.headline); Spacer(); Text(source["cited"] as? Bool == true ? "Cited" : "Not cited").font(.caption).foregroundStyle(source["cited"] as? Bool == true ? Color.green : Color.secondary) }
                            Text((source["authors"] as? [String] ?? []).joined(separator:"; ")+" · "+String(describing:source["year"] ?? ""))
                            Text((source["id"] as? String ?? "")+" · "+(source["has_evidence"] as? Bool == true ? "Supporting text available" : "Metadata only — needs evidence")).font(.caption).foregroundStyle(.secondary)
                            if let links=source["author_links"] as? [[String:Any]], !links.isEmpty {
                                Text("Secondary discussion: "+links.compactMap { $0["author"] as? String }.joined(separator:"; ")).font(.caption).foregroundStyle(accent)
                            }
                            if let warning=source["identity_warning"] as? String { Text(warning).font(.caption).foregroundStyle(.orange) }
                            if let access=source["access_status"] as? String { Text(access).font(.caption).foregroundStyle(.secondary) }
                            if let links=source["access_links"] as? [[String:Any]] {
                                ForEach(Array(links.enumerated()),id:\.offset) { _,link in
                                    if let value=link["url"] as? String, let url=URL(string:value), url.scheme == "https" {
                                        Link(link["label"] as? String ?? "Open source",destination:url).font(.caption)
                                    }
                                }
                            }
                            if let doi=source["doi"] as? String, !doi.isEmpty { Text("DOI: "+doi).font(.caption) }
                        }.frame(maxWidth:.infinity,alignment:.leading).padding(6).textSelection(.enabled)
                    }
                }
            }
        } else {
            Text("Candidates are search leads, not a formatted works-cited list. Importing does not guarantee inclusion. Add authors under Required authors in Brief when they must be cited.").font(.callout).foregroundStyle(.secondary)
            if candidates.isEmpty { Text("No reference candidates yet.").foregroundStyle(.secondary) }
            LazyVStack(alignment:.leading,spacing:10) { ForEach(Array(candidates.filter { search.isEmpty || $0.localizedCaseInsensitiveContains(search) }.enumerated()),id:\.offset) { _,text in Text(text).textSelection(.enabled); Divider() } }
        }
    } }
}

struct BibliographyImportView: View {
    @EnvironmentObject var studio: Studio
    @State var mode="replan"
    var body: some View { VStack(alignment:.leading,spacing:16) {
        Text("Review bibliography").font(.title2.bold())
        Text(studio.bibliographyName).foregroundStyle(.secondary)
        Text("Separate references with a blank line. Remove headings and join wrapped references, especially in PDFs. These entries will be added to Possible citations; duplicates are skipped.").font(.callout)
        TextEditor(text:$studio.bibliographyText).font(.body).frame(minHeight:260).border(Color.gray.opacity(0.3))
        if !studio.sections.isEmpty {
            Picker("Use these references",selection:$mode) {
                Text("Replan manuscript from this bibliography").tag("replan")
                Text("Keep current draft for citation repair").tag("repair")
            }.pickerStyle(.radioGroup)
        }
        Text(mode == "replan" ? "Adding new references archives any existing draft and restarts planning. The next abstract and manuscript will use the expanded bibliography." : "Existing prose stays intact. Next, use Repair → Start citation repair to research these candidates and address citation gaps.").font(.callout).foregroundStyle(.secondary)
        Text("Up to 1,000 candidates / 180,000 characters per project. Bibliography text supplies research data, not instructions or evidence of a work’s claims.").font(.caption).foregroundStyle(.secondary)
        HStack { Button("Cancel",role:.cancel) { studio.showBibliography=false }; Spacer(); Button("Add references") {
            studio.run("import_bibliography",extra:["text":studio.bibliographyText,"mode":mode]) { _ in studio.showBibliography=false; studio.page="Bibliography" }
        }.buttonStyle(.borderedProminent).disabled(studio.bibliographyText.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty) }
    }.padding(24).frame(width:720).disabled(studio.busy).interactiveDismissDisabled(studio.busy) }
}


struct LuckyDie: View {
    let value:Int
    var body: some View {
        Canvas { context,size in
            let points:[CGPoint] = value == 3 ? [CGPoint(x:0.25,y:0.25),CGPoint(x:0.5,y:0.5),CGPoint(x:0.75,y:0.75)] : [CGPoint(x:0.25,y:0.25),CGPoint(x:0.75,y:0.25),CGPoint(x:0.25,y:0.75),CGPoint(x:0.75,y:0.75)]
            for point in points { context.fill(Path(ellipseIn:CGRect(x:point.x*size.width-3.5,y:point.y*size.height-3.5,width:7,height:7)),with:.color(accent)) }
        }.frame(width:44,height:44).background(Color.white,in:RoundedRectangle(cornerRadius:9)).overlay(RoundedRectangle(cornerRadius:9).stroke(accent.opacity(0.3))).shadow(color:.black.opacity(0.12),radius:3,y:2)
        .accessibilityLabel("Die showing \(value)")
    }
}
struct GenerateView: View {
    @EnvironmentObject var studio: Studio
    @State var rolling=false
    @State var turns=0.0
    @State var confirmRandom=false
    @State var confirmApply=false
    let kinds=[("titles","Titles"),("ideas","Ideas"),("authors","Authors"),("bibliography","Bibliography"),("abstract","Abstract"),("contents","Table of contents")]
    var proposal:[String:Any] { ((studio.project["development"] as? [String:Any])?["proposals"] as? [String:[String:Any]])?[studio.generationKind] ?? [:] }
    var canApply:Bool {
        let text=studio.generationText.trimmingCharacters(in:.whitespacesAndNewlines)
        guard !studio.busy, !studio.dirty, !text.isEmpty, text.count<=180000, proposal["can_apply"] as? Bool == true else { return false }
        if studio.generationKind == "titles" { return (proposal["titles"] as? [String] ?? []).contains(text) }
        if studio.generationKind == "abstract" {
            let pattern="\\b[\\w]+(?:[’'-][\\w]+)*\\b"
            let count=(try? NSRegularExpression(pattern:pattern))?.numberOfMatches(in:text,range:NSRange(text.startIndex...,in:text)) ?? 0
            return (250...300).contains(count) && !text.contains("[@")
        }
        if studio.generationKind == "authors" {
            let names=text.replacingOccurrences(of:";",with:"\n").split(separator:"\n").map { $0.trimmingCharacters(in:.whitespacesAndNewlines) }.filter { !$0.isEmpty }
            return !names.isEmpty && Set(names+(studio.brief["important_authors"] as? [String] ?? [])).count<=999
        }
        if studio.generationKind == "bibliography" {
            if !(studio.brief["sources_file"] as? String ?? "").isEmpty { return false }
            let blocks=text.replacingOccurrences(of:"\\n\\s*\\n",with:"\u{001F}",options:.regularExpression).components(separatedBy:"\u{001F}").map { $0.split(whereSeparator: { $0.isWhitespace }).joined(separator:" ") }.filter { !$0.isEmpty }
            guard blocks.count<=1000, blocks.allSatisfy({ $0.count<=4000 }) else { return false }
            let all=Set(blocks+(studio.brief["possible_citations"] as? [String] ?? []))
            return all.count<=1000 && all.reduce(0,{ $0+$1.count+2 })<=180000
        }
        if studio.generationKind == "contents" && studio.isBook { return text.count<=60000 }
        return true
    }
    var body: some View { Panel(title:"Ideas",subtitle:"Develop the pieces of your article or book with your selected model, before writing the manuscript.") {
        HStack { Label(studio.provider+" / "+studio.model,systemImage:"cpu").foregroundStyle(.secondary); Spacer(); Button("Provider settings") { studio.page="Settings" } }
        Text("Start with any amount of detail in Brief. Generate a suggestion, edit it, and apply it when ready. Uploaded document analysis and previous suggestions help guide the next step.").font(.callout).foregroundStyle(.secondary)
        Picker("Develop",selection:Binding(get:{studio.generationKind},set:{studio.generationKind=$0;studio.refreshProposal()})) { ForEach(kinds,id:\.0) { key,label in Text(label).tag(key) } }.pickerStyle(.segmented).disabled(studio.busy)
        HStack {
            Button(studio.generationKind == "titles" ? "Generate 10 titles" : (studio.generationText.isEmpty ? "Generate suggestion" : "Generate another suggestion")) { studio.inference("develop",extra:["kind":studio.generationKind]) }.buttonStyle(.borderedProminent).disabled(studio.busy || studio.dirty)
            Text("Suggestions are saved; generating alone does not change the manuscript.").font(.caption).foregroundStyle(.secondary)
        }
        if studio.generationKind == "bibliography" { Text("The model proposes search queries; Crossref supplies up to 40 starter references. Check relevance before applying. This is a starting bibliography, not the full manuscript citation target.").font(.callout).foregroundStyle(.secondary) }
        if studio.generationKind == "abstract" { Text("This is a provisional 250–300 word abstract. Applying it adds guidance to Brief; Create researched abstract below develops the formal abstract with the source ledger.").font(.callout).foregroundStyle(.secondary) }
        if studio.generationKind == "authors" { Text("Review one name per line. Applying adds these names to Required authors, so each becomes a citation requirement.").font(.callout).foregroundStyle(.secondary) }
        if studio.generationKind == "titles" {
            Text("Choose one title, then apply it to Brief. You can edit the chosen title later in Brief.").font(.callout).foregroundStyle(.secondary)
            ForEach(proposal["titles"] as? [String] ?? [],id: \.self) { title in
                Button { studio.generationText=title } label: { HStack(alignment:.top) { Image(systemName:studio.generationText == title ? "largecircle.fill.circle" : "circle"); Text(title).multilineTextAlignment(.leading); Spacer() } }.buttonStyle(.plain).padding(.vertical,5).disabled(studio.busy)
            }
        } else {
        FieldEditor(label:"Your working suggestion",hint:"Edit before applying. Generate another suggestion or switch tabs to reload saved text; unapplied edits are not saved.",text:$studio.generationText,height:270).disabled(studio.busy)
        }
        if !proposal.isEmpty && proposal["can_apply"] as? Bool != true { Text("The brief changed. Generate a fresh suggestion before applying.").font(.caption).foregroundStyle(.secondary) }
        HStack {
            Button("Apply to brief…") { confirmApply=true }.buttonStyle(.borderedProminent).tint(.blue).disabled(!canApply)
            Spacer()
            Button("Create researched abstract") { studio.page="Abstract";studio.inference("abstract") }.disabled(studio.busy || studio.dirty)
            Button("Generate manuscript") { studio.page="Manuscript";studio.inference("generate") }.disabled(studio.busy || studio.dirty)
        }
        Divider().padding(.vertical,6)
        HStack(spacing:20) {
            Button {
                guard !rolling else { return }
                rolling=true
                withAnimation(.spring(response:0.6,dampingFraction:0.5)) { turns += 720 }
                DispatchQueue.main.asyncAfter(deadline:.now()+0.7) { rolling=false;confirmRandom=true }
            } label: {
                HStack(spacing:9) { LuckyDie(value:3).rotationEffect(.degrees(turns)); LuckyDie(value:4).rotationEffect(.degrees(-turns)) }.padding(10)
            }.buttonStyle(.plain).disabled(studio.busy || studio.dirty || rolling).accessibilityLabel("Lucky seven: roll to generate a manuscript").help("Roll lucky seven — confirmation required")
            VStack(alignment:.leading,spacing:5) {
                Text("Lucky seven").font(.title3.bold())
                Text("Roll for a fresh direction and a manuscript. Your entered constraints stay in place; the model fills gaps and develops a new angle.").foregroundStyle(.secondary)
            }
        }
        Text("AI-assisted suggestions require review. Random generation uses the same citation and evidence checks as ordinary generation, and may pause when sources are insufficient.").font(.caption).foregroundStyle(.secondary)
        if studio.dirty { Text("Save Brief or Abstract edits before generating.").foregroundStyle(.orange) }
    }
    .alert("Apply this suggestion?",isPresented:$confirmApply) {
        Button("Cancel",role:.cancel) { }
        Button("Apply to brief") { studio.run("apply_development",extra:["kind":studio.generationKind,"text":studio.generationText]) }
    } message: { Text(studio.generationKind == "titles" ? "This sets the manuscript title and preserves existing prose." : "This updates the project brief. If guidance changes, any existing draft is archived and planning starts again. Review the suggestion first.") }
    .confirmationDialog("Proceed with lucky-seven generation?",isPresented:$confirmRandom,titleVisibility:.visible) {
        Button("Generate ideas and manuscript") { studio.inference("random_generate",extra:["confirmed":true]) }
        Button("Cancel",role:.cancel) { }
    } message: { Text("KOALA will contact \(studio.provider) / \(studio.model), preserve your entered constraints, add a random research direction, then generate the abstract and manuscript. Any existing draft will be archived and restarted. This can involve many paid API requests, especially for a book. Stop and resume using the activity bar and Manuscript page.") }
    }
}


struct PromptsView: View {
    @EnvironmentObject var studio: Studio
    @State var templates:[[String:String]]=[]
    @State var selected="default"
    @State var notice=""
    var defaultPrompt:String { studio.project["default_writing_prompt"] as? String ?? "" }
    var promptText:Binding<String> { Binding(get:{ studio.value("writing_prompt").trimmingCharacters(in:.whitespacesAndNewlines).isEmpty ? defaultPrompt : studio.value("writing_prompt") },set:{ studio.binding("writing_prompt").wrappedValue=$0 }) }
    var body: some View { Panel(title:"Writing prompts",subtitle:"Edit the main writing prompt, or build a library of custom prompts for different projects.") {
        Text("This is the writing prompt beginning ‘You are an academic writer and editor…’. KOALA adds its citation, evidence, and output-format requirements separately. Your Brief’s Writing style can refine the selected prompt.").font(.callout).foregroundStyle(.secondary)
        GroupBox("Template library") {
            VStack(alignment:.leading,spacing:10) {
                Picker("Saved prompts",selection:$selected) { ForEach(templates,id:\.self) { row in Text(row["name"] ?? "Prompt").tag(row["id"] ?? "") } }
                HStack {
                    Button("Load into editor") {
                        if let row=templates.first(where:{$0["id"]==selected}) {
                            studio.binding("writing_prompt").wrappedValue=row["id"] == "default" ? "" : (row["text"] ?? "")
                            studio.binding("writing_prompt_name").wrappedValue=row["name"] ?? "Custom prompt"
                            notice="Template loaded. Save project prompt to apply it."
                        }
                    }.disabled(templates.isEmpty)
                    Button("Save as new template") { saveTemplate(update:false) }
                    Button("Update selected template") { saveTemplate(update:true) }.disabled(selected=="default" || templates.isEmpty)
                }
                Text("Templates are available across projects on this Mac. Each project keeps its own copy, so editing a template does not change other projects.").font(.caption).foregroundStyle(.secondary)
            }.padding(8)
        }
        TextField("Prompt name",text:studio.binding("writing_prompt_name")).textFieldStyle(.roundedBorder)
        HStack {
            Button("Save project prompt") { studio.run("save_brief",extra:["brief":studio.brief]) { _ in notice="Project prompt saved. Future generation will use it." } }.buttonStyle(.borderedProminent).disabled(!studio.briefDirty)
            Button("Restore KOALA default") { studio.binding("writing_prompt").wrappedValue="";studio.binding("writing_prompt_name").wrappedValue="KOALA default";notice="Default restored in the editor. Save project prompt to apply it." }
            Spacer()
            Text(studio.briefDirty ? "Unsaved brief / prompt changes" : "Saved").font(.caption).foregroundStyle(.secondary)
        }
        FieldEditor(label:"Main writing prompt",hint:"Up to 30,000 characters. Saving also saves any other pending Brief edits.",text:promptText,height:420)
        if !notice.isEmpty { Text(notice).font(.callout).foregroundStyle(accent) }
        Text("Prompt-only changes preserve completed prose and checkpoints. The new prompt applies to future abstracts, article and book drafting, Generate suggestions, and citation repair. Existing text is not automatically rewritten. Save before starting generation.").font(.callout).foregroundStyle(.secondary)
    }.disabled(studio.busy || studio.abstractDirty).onAppear {
        studio.run("prompt_library") { data in templates=data["templates"] as? [[String:String]] ?? [] }
    } }
    func saveTemplate(update:Bool) {
        var extra:[String:Any]=["name":studio.value("writing_prompt_name"),"text":promptText.wrappedValue]
        if update { extra["id"]=selected }
        studio.run("save_prompt_template",extra:extra) { data in
            templates=data["templates"] as? [[String:String]] ?? []
            selected=data["saved_id"] as? String ?? selected
            notice="Template saved to your library. Save project prompt to apply the current text to this project."
        }
    }
}


struct RenameProjectView: View {
    @EnvironmentObject var studio:Studio
    @Environment(\.dismiss) var dismiss
    @State var name=""
    var body: some View { VStack(alignment:.leading,spacing:16) {
        Text("Rename project").font(.title2.bold())
        if let error=studio.error { Text(error).foregroundStyle(.red) }
        TextField("Project name",text:$name).textFieldStyle(.roundedBorder)
        Text("This renames the project and its folder, updates saved internal paths, and replaces the old Recent projects entry. Your manuscript title and text stay unchanged.").font(.callout).foregroundStyle(.secondary)
        Text(studio.folder).font(.caption).textSelection(.enabled)
        HStack { Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction); Spacer(); Button("Rename") {
            studio.run("rename_project",extra:["name":name]) { _ in studio.activity=[];studio.log("Project renamed.");dismiss() }
        }.buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction).disabled(name.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty || name.count>120) }
    }.padding(24).frame(width:500).disabled(studio.busy).onAppear { name=studio.projectName(studio.folder) } }
}

struct DataWorkspaceView: View {
    @EnvironmentObject var studio: Studio
    @State private var selected = ""
    @State private var mode = "summary"
    @State private var column = ""
    @State private var group = ""
    @State private var question = ""
    @State private var placement = "findings"
    @State private var notes = ""
    var datasets: [[String:Any]] { (studio.project["data_workspace"] as? [String:Any])?["datasets"] as? [[String:Any]] ?? [] }
    var current: [String:Any] { datasets.first { $0["id"] as? String == selected } ?? [:] }
    var body: some View { Panel(title:"Data",subtitle:"Analyze your data and choose findings to incorporate into the manuscript.") {
        Button("Upload data…") {
            let panel=NSOpenPanel(); panel.allowedContentTypes=[.plainText,.json,UTType(filenameExtension:"csv")!,UTType(filenameExtension:"tsv")!]
            if panel.runModal() == .OK, let url=panel.url { studio.run("import_data",extra:["path":url.path]) }
        }.buttonStyle(.borderedProminent).disabled(studio.busy || studio.dirty)
        Text("CSV / TSV with headers, flat JSON records, or UTF-8 TXT. Up to 20 MB, 100,000 rows and 200 columns. Original files are copied into the project. Statistics run locally; model analysis sends computed summaries and up to the first 100 rows or 30,000 text characters to your selected provider.").font(.caption).foregroundStyle(.secondary)
        Picker("Dataset",selection:$selected) {
            Text("Choose a dataset").tag("")
            ForEach(Array(datasets.enumerated()),id: \.offset) { _,item in Text(item["name"] as? String ?? "Dataset").tag(item["id"] as? String ?? "") }
        }
        if !current.isEmpty {
            Text("\(current["rows"] as? Int ?? 0) rows · Columns: \((current["columns"] as? [String] ?? []).joined(separator:", "))").font(.caption).textSelection(.enabled)
            Picker("Analysis",selection:$mode) {
                Text("Descriptive statistics and missing values").tag("summary")
                Text("Category frequencies").tag("frequencies")
                Text("Compare groups (descriptive)").tag("compare")
                Text("Interpret data with model").tag("interpret")
                Text("Explore themes with model").tag("themes")
            }
            if mode == "frequencies" || mode == "compare" { TextField("Column name (exact header)",text:$column) }
            if mode == "compare" { TextField("Grouping column (exact header)",text:$group) }
            if mode == "interpret" || mode == "themes" { TextField("Research question or analysis instructions",text:$question) }
            Button("Run analysis") {
                let args:[String:Any] = ["dataset":selected,"mode":mode,"column":column,"group":group,"question":question]
                if mode == "interpret" || mode == "themes" { studio.inference("analyze_data",extra:args) } else { studio.run("analyze_data",extra:args) }
            }.disabled(studio.busy || studio.dirty)
            Divider()
            Picker("Integrate into",selection:$placement) { ForEach(["methods","findings","discussion","appendix"],id: \.self) { Text($0.capitalized).tag($0) } }
            TextField("Integration guidance (optional)",text:$notes)
            Text("Review results before including them. Selected findings guide future abstract and manuscript generation. Existing prose stays in place; completed sections are not automatically rewritten. Model interpretations are provisional and sampled; numeric comparisons do not establish statistical significance or causation.").font(.callout).foregroundStyle(.secondary)
            ForEach(Array((current["analyses"] as? [[String:Any]] ?? []).enumerated()),id: \.offset) { _,analysis in
                GroupBox(analysis["mode"] as? String ?? "Analysis") {
                    VStack(alignment:.leading,spacing:10) {
                        Text(analysis["result"] as? String ?? "").textSelection(.enabled).frame(maxWidth:.infinity,alignment:.leading)
                        if analysis["included"] as? Bool == true { Text("Included in \(analysis["placement"] as? String ?? "findings")").foregroundStyle(accent) }
                        Button(analysis["included"] as? Bool == true ? "Exclude from generation" : "Include these findings") {
                            studio.run("integrate_data",extra:["dataset":selected,"analysis":analysis["id"] as? String ?? "","included":!(analysis["included"] as? Bool ?? false),"placement":placement,"notes":notes])
                        }.disabled(studio.busy || studio.dirty)
                    }.padding(8)
                }
            }
        }
    }.onChange(of: studio.project["folder"] as? String) { _ in selected="" } }
}

struct StyleView: View {
    @EnvironmentObject var studio: Studio
    @State private var inspiration = ""
    @State private var traits = ""
    var customStyle: String {
        let name=inspiration.trimmingCharacters(in:.whitespacesAndNewlines)
        let details=traits.trimmingCharacters(in:.whitespacesAndNewlines)
        if name.isEmpty { return details }
        if details.isEmpty { return "Inspiration: "+name+". Infer suitable broad writing traits from this influence and adapt them to the academic subject and audience." }
        return "Inspiration: "+name+". Apply these broad traits: "+details
    }
    func addCustomStyle() {
        guard !customStyle.isEmpty else { return }
        add(customStyle); inspiration=""; traits=""
    }
    func add(_ text:String) {
        let old=studio.value("style_guidance").trimmingCharacters(in:.whitespacesAndNewlines)
        studio.binding("style_guidance").wrappedValue=old.isEmpty ? text : old+"\n\n"+text
    }
    var body: some View { Panel(title:"Style",subtitle:"Describe the voice and writing traits you want for your academic project.") {
        GroupBox("Your own inspiration") {
            VStack(alignment:.leading,spacing:10) {
                TextField("Author or influence (optional)",text:$inspiration)
                FieldEditor(label:"Traits to draw on (optional)",hint:"An author or influence alone is enough. Add traits only if you want to guide the interpretation.",text:$traits,height:100)
                Button("Add custom inspiration") { addCustomStyle() }.disabled(customStyle.isEmpty)
            }.padding(8)
        }
        FieldEditor(label:"Project style",hint:"Edit, blend, or remove traits. This is the same Writing style field shown in Brief.",text:studio.binding("style_guidance"),height:220)
        HStack {
            Button("Save style") { addCustomStyle(); studio.run("save_brief",extra:["brief":studio.brief]) }.buttonStyle(.borderedProminent).disabled(!studio.briefDirty && customStyle.isEmpty)
            Button("Clear style") { inspiration=""; traits=""; studio.binding("style_guidance").wrappedValue="" }
            Text(studio.briefDirty || !customStyle.isEmpty ? "Unsaved changes" : "Saved").font(.caption).foregroundStyle(.secondary)
        }
        Text("Styles adapt broad writing traits to academic prose; they do not copy passages or impersonate authors. For living authors, use general characteristics rather than a distinctive voice. Evidence and citation rules always apply. Saving also saves pending Brief edits. Style-only changes preserve existing manuscript text and apply to future generation; existing prose is not automatically rewritten.").font(.callout).foregroundStyle(.secondary)
    }.disabled(studio.busy || studio.abstractDirty) }
}

struct RewriteView: View {
    @EnvironmentObject var studio: Studio
    @State private var topic = ""
    @State private var discipline = ""
    @State private var ideas = ""
    @State private var guidance = ""
    @State private var style = ""
    @State private var target = ""
    @State private var confirmApply = false
    var state:[String:Any] { studio.project["rewrite"] as? [String:Any] ?? [:] }
    var parameters:[String:Any] { ["topic":topic,"discipline":discipline,"important_ideas":ideas.split(separator:";").map { $0.trimmingCharacters(in:.whitespacesAndNewlines) }.filter { !$0.isEmpty },"research_guidance":guidance,"style_guidance":style,"target_words":Int(target) ?? 0] }
    var body:some View { Panel(title:"Rewrite manuscript",subtitle:"Revise your project parameters and create a separate rewritten draft for review.") {
        Text("Edit parameters here before saving a changed Brief. Rewrite preserves the existing chapter and section structure and works from the current manuscript and source evidence. It does not discover new sources. For a new chapter structure, use the normal planning and generation workflow.").font(.callout).foregroundStyle(.secondary)
        TextField("Subject / topic",text:$topic)
        TextField("Discipline",text:$discipline)
        TextField("Important ideas (separated by semicolons)",text:$ideas)
        TextField("Target manuscript word count",text:$target)
        FieldEditor(label:"Revised research guidance and emphasis",hint:"Describe what should change in the argument or treatment.",text:$guidance,height:120)
        FieldEditor(label:"Revised style",hint:"Changes apply to this rewrite. The current manuscript remains active until you accept the result.",text:$style,height:120)
        HStack {
            Button("Start new rewrite") { studio.inference("rewrite_manuscript",extra:["parameters":parameters,"restart":true]) }.buttonStyle(.borderedProminent).disabled(studio.busy || studio.dirty || studio.sections.isEmpty || Int(target)==nil)
            if !state.isEmpty && state["complete"] as? Bool != true && state["applied"] as? Bool != true {
                Button("Resume saved rewrite") { studio.inference("rewrite_manuscript") }.disabled(studio.busy || studio.dirty)
            }
        }
        Text("Each pass keeps an original backup, rewrites section by section, and saves progress. Resume uses the saved rewrite parameters; start a new rewrite to change them. Unsupported citation or quotation edits retain the original section for review. Word-count and citation-coverage shortfalls are review notes, not reasons to stop. Partial manuscripts rewrite only their completed sections.").font(.caption).foregroundStyle(.secondary)
        if let count=state["processed"] as? Int {
            Text("\(count) of \(state["total"] as? Int ?? 0) sections processed").font(.headline)
            HStack {
                if let path=state["report"] as? String { Button("Review original and rewrite") { NSWorkspace.shared.open(URL(fileURLWithPath:path)) } }
                if let path=state["archive"] as? String { Button("Show original backup") { NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath:path)]) } }
                Button("Use rewritten manuscript") { confirmApply=true }.disabled(studio.busy || studio.dirty || state["complete"] as? Bool != true || state["applied"] as? Bool == true)
            }
            if state["applied"] as? Bool == true { Text("Rewrite applied. Export again to create updated files.").foregroundStyle(accent); Button("Go to export") { studio.page="Export" } }
        }
    }.onAppear { loadFields() }.onChange(of:studio.folder) { _ in loadFields() }
    .confirmationDialog("Use the rewritten manuscript and its revised parameters? The original remains in the backup.",isPresented:$confirmApply) {
        Button("Use rewritten manuscript") { studio.run("apply_rewrite") }
        Button("Cancel",role:.cancel) {}
    } }
    func loadFields() {
        let saved=state["applied"] as? Bool == true ? [:] : (state["parameters"] as? [String:Any] ?? [:])
        let brief=studio.brief.merging(saved) { _,new in new }
        topic=brief["topic"] as? String ?? "";discipline=brief["discipline"] as? String ?? ""
        ideas=(brief["important_ideas"] as? [String] ?? []).joined(separator:"; ")
        guidance=brief["research_guidance"] as? String ?? "";style=brief["style_guidance"] as? String ?? ""
        target=String(brief["target_words"] as? Int ?? 6500)
    }
}
