package main

import (
	"archive/zip"
	"crypto/rand"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	_ "github.com/lib/pq"
)

var db *sql.DB

type Token struct {
	ID          int       `json:"id"`
	TokenStr    string    `json:"token_string"`
	WorkspaceID int       `json:"workspace_id"`
	Status      string    `json:"status"`
	CreatedAt   time.Time `json:"created_at"`
}

type User struct {
	Username string `json:"username"`
	Password string `json:"password"`
	Nama     string `json:"nama"`
}

type Workspace struct {
	ID            int               `json:"id"`
	Name          string            `json:"name"`
	OwnerUsername string            `json:"owner_username,omitempty"`
	IsCollab      bool              `json:"is_collab"`
	Members       []WorkspaceMember `json:"members,omitempty"`
	MyStatus      string            `json:"my_status,omitempty"`
	MyInvitedBy   string            `json:"my_invited_by,omitempty"`
	CanOpen       bool              `json:"can_open"`
	CanInvite     bool              `json:"can_invite"`
	CanDelete     bool              `json:"can_delete"`
	CanManage     bool              `json:"can_manage_collab"`
}

type WorkspaceMember struct {
	Username  string `json:"username"`
	Role      string `json:"role"`
	InvitedBy string `json:"invited_by,omitempty"`
	Status    string `json:"status"`
	CanInvite bool   `json:"can_invite"`
	CanOpen   bool   `json:"can_open"`
}

type Dataset struct {
	ID          int       `json:"id"`
	WorkspaceID int       `json:"workspace_id"`
	Name        string    `json:"name"`
	GeomType    string    `json:"geom_type"`
	SRID        int       `json:"srid"`
	TableName   string    `json:"table_name"`
	FillColor   string    `json:"fill_color"`
	StrokeColor string    `json:"stroke_color"`
	BBox        []float64 `json:"bbox"`
}

type Styling struct {
	DatasetID   int    `json:"dataset_id"`
	FillColor   string `json:"fill_color"`
	StrokeColor string `json:"stroke_color"`
}

type CollectionLink struct {
	Href string `json:"href"`
	Rel  string `json:"rel"`
	Type string `json:"type"`
}

func initDB() {
	connStr := fmt.Sprintf("host=%s port=%s user=%s password=%s dbname=%s sslmode=disable",
		os.Getenv("DB_HOST"), os.Getenv("DB_PORT"), os.Getenv("DB_USER"), os.Getenv("DB_PASSWORD"), os.Getenv("DB_NAME"))
	
	if os.Getenv("DB_HOST") == "" {
		connStr = "host=localhost port=5432 user=gisnas_user password=gisnas_password dbname=gisnas_db sslmode=disable"
	}

	var err error
	db, err = sql.Open("postgres", connStr)
	if err != nil {
		log.Fatal("Gagal koneksi ke database:", err)
	}

	// Create all necessary tables for GISNAS
	queries := []string{
		`CREATE EXTENSION IF NOT EXISTS postgis_topology;`,
		`CREATE TABLE IF NOT EXISTS users (
			id SERIAL PRIMARY KEY,
			username VARCHAR(50) UNIQUE NOT NULL,
			password VARCHAR(255) NOT NULL,
			role VARCHAR(20) DEFAULT 'user'
		);`,
		`CREATE TABLE IF NOT EXISTS workspaces (
			id SERIAL PRIMARY KEY,
			name VARCHAR(255) NOT NULL,
			owner_username VARCHAR(50),
			is_collab BOOLEAN DEFAULT FALSE,
			created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
		);`,
		`CREATE TABLE IF NOT EXISTS workspace_members (
			id SERIAL PRIMARY KEY,
			workspace_id INT REFERENCES workspaces(id) ON DELETE CASCADE,
			username VARCHAR(50) NOT NULL,
			role VARCHAR(20) DEFAULT 'editor',
			status VARCHAR(20) DEFAULT 'accepted',
			can_invite BOOLEAN DEFAULT TRUE,
			can_open BOOLEAN DEFAULT TRUE,
			invited_by VARCHAR(50),
			created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
			UNIQUE(workspace_id, username)
		);`,
		`CREATE TABLE IF NOT EXISTS api_tokens (
			id SERIAL PRIMARY KEY,
			token_string VARCHAR(255) UNIQUE NOT NULL,
			workspace_id INT REFERENCES workspaces(id),
			status VARCHAR(20) DEFAULT 'RUNNING',
			created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
		);`,
		`CREATE TABLE IF NOT EXISTS datasets (
			id SERIAL PRIMARY KEY,
			workspace_id INT REFERENCES workspaces(id),
			name VARCHAR(255) NOT NULL,
			geom_type VARCHAR(50),
			srid INT DEFAULT 4326,
			table_name VARCHAR(255),
			created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
		);`,
		`CREATE TABLE IF NOT EXISTS stylings (
			id SERIAL PRIMARY KEY,
			dataset_id INT,
			fill_color VARCHAR(20),
			stroke_color VARCHAR(20)
		);`,
		`CREATE OR REPLACE FUNCTION update_timestamp_column()
		RETURNS TRIGGER AS $$
		BEGIN
			NEW.update_gn = CURRENT_TIMESTAMP;
			RETURN NEW;
		END;
		$$ language 'plpgsql';`,
	}

	for _, q := range queries {
		if _, err := db.Exec(q); err != nil {
			log.Fatal("Gagal membuat tabel:", err)
		}
	}

	// Ensure table_name column exists for older databases
	db.Exec("ALTER TABLE datasets ADD COLUMN IF NOT EXISTS table_name VARCHAR(255)")
	db.Exec("ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS owner_username VARCHAR(50)")
	db.Exec("ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS is_collab BOOLEAN DEFAULT FALSE")
	db.Exec("ALTER TABLE workspace_members ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'accepted'")
	db.Exec("ALTER TABLE workspace_members ADD COLUMN IF NOT EXISTS can_invite BOOLEAN DEFAULT TRUE")
	db.Exec("ALTER TABLE workspace_members ADD COLUMN IF NOT EXISTS can_open BOOLEAN DEFAULT TRUE")
	db.Exec("UPDATE workspace_members SET status = 'accepted' WHERE status IS NULL OR status = ''")
	db.Exec("UPDATE workspace_members SET can_invite = TRUE WHERE can_invite IS NULL")
	db.Exec("UPDATE workspace_members SET can_open = TRUE WHERE can_open IS NULL")
	
	db.Exec(`CREATE TABLE IF NOT EXISTS feature_history (
		id SERIAL PRIMARY KEY,
		table_name VARCHAR(255),
		feature_id INT,
		action VARCHAR(10),
		old_geom JSONB,
		new_geom JSONB,
		old_properties JSONB,
		new_properties JSONB,
		changed_by VARCHAR(255),
		created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
	)`)
        // Add columns for user management (IP tracking & blocking)
        db.Exec("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_ip VARCHAR(45)")
        db.Exec("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN DEFAULT FALSE")
        db.Exec("ALTER TABLE users ADD COLUMN IF NOT EXISTS blocked_at TIMESTAMP")
        db.Exec("ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
	db.Exec("ALTER TABLE users ADD COLUMN IF NOT EXISTS nama VARCHAR(100) DEFAULT ''")
        db.Exec("ALTER TABLE users ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP")


	
	// Seed Superadmin account from .env
	adminUser := os.Getenv("ADMIN_USER")
	adminPass := os.Getenv("ADMIN_PASS")
	if adminUser == "" { adminUser = "superadmin" }
	if adminPass == "" { adminPass = "admin123" }

	db.Exec("INSERT INTO users (username, password, role) VALUES ($1, $2, 'superadmin') ON CONFLICT (username) DO UPDATE SET password = EXCLUDED.password", adminUser, adminPass)
	
	fmt.Println("Database PostGIS tersambung, Skema 100% selesai dibuat.")
}

// ================= AUTHENTICATION =================
func publicConfigHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != "GET" {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	registrationEnabled := os.Getenv("REGISTRATION_ENABLED") != "false"
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]bool{"registration_enabled": registrationEnabled})
}

func loginHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != "POST" {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var user User
	if err := json.NewDecoder(r.Body).Decode(&user); err != nil {
		http.Error(w, `{"error": "Format JSON tidak valid"}`, http.StatusBadRequest)
		return
	}
	
	var role string
	var isBlocked bool
	err := db.QueryRow("SELECT role, COALESCE(is_blocked, FALSE) FROM users WHERE username = $1 AND password = $2", user.Username, user.Password).Scan(&role, &isBlocked)
	if err != nil {
		http.Error(w, `{"error": "Username atau Password salah"}`, http.StatusUnauthorized)
		return
	}
        if isBlocked {
                http.Error(w, `{"error": "Akun anda telah diblokir oleh superadmin. Silakan hubungi administrator."}`, http.StatusForbidden)
                return
        }

	
	w.Header().Set("Content-Type", "application/json")
	
	// Create JWT token using secret from .env (MVP simple mock generation).
	// Guard short JWT_SECRET values so login never panics on slicing.
	jwtSecret := os.Getenv("JWT_SECRET")
	if jwtSecret == "" { jwtSecret = "default_secret" }
	secretPreview := jwtSecret
	if len(secretPreview) > 10 {
		secretPreview = secretPreview[:10]
	}
	mockToken := fmt.Sprintf("JWT-GISNAS-%s-%s", user.Username, secretPreview)

	var nama string
	db.QueryRow("SELECT COALESCE(nama, '') FROM users WHERE username = $1", user.Username).Scan(&nama)
	w.Write([]byte(fmt.Sprintf(
		`{"token": "%s", "role": "%s", "username": "%s", "nama": "%s", "message": "Login berhasil"}`,
		mockToken, role, user.Username, nama,
	)))
}

func requestUsername(r *http.Request) string {
	if u := strings.TrimSpace(r.Header.Get("X-GISNAS-User")); u != "" {
		return u
	}
	return strings.TrimSpace(r.URL.Query().Get("username"))
}

func requestRole(r *http.Request) string {
	if role := strings.TrimSpace(r.Header.Get("X-GISNAS-Role")); role != "" {
		return role
	}
	return strings.TrimSpace(r.URL.Query().Get("role"))
}

func workspaceCanManage(owner string, role string, username string) bool {
	if role == "superadmin" {
		return true
	}
	return owner != "" && owner == username
}

func workspaceCanInvite(owner string, role string, username string, workspaceID int) bool {
	if workspaceCanManage(owner, role, username) {
		return true
	}
	status, _, canInvite, canOpen, found := workspaceMemberPermissions(workspaceID, username)
	if !found {
		return false
	}
	return status == "accepted" && canOpen && canInvite
}

func refreshWorkspaceCollabFlag(workspaceID int) {
	var n int
	db.QueryRow(
		`SELECT COUNT(*) FROM workspace_members WHERE workspace_id = $1 AND COALESCE(status, 'accepted') = 'accepted' AND COALESCE(can_open, TRUE) = TRUE`,
		workspaceID,
	).Scan(&n)
	isCollab := n > 1
	db.Exec(`UPDATE workspaces SET is_collab = $1 WHERE id = $2`, isCollab, workspaceID)
}

func loadWorkspaceMembers(workspaceID int) []WorkspaceMember {
	rows, err := db.Query(
		`SELECT username, role, COALESCE(invited_by, ''), COALESCE(status, 'accepted'), COALESCE(can_invite, TRUE), COALESCE(can_open, TRUE) FROM workspace_members
		 WHERE workspace_id = $1 AND COALESCE(status, 'accepted') = 'accepted'
		 ORDER BY CASE role WHEN 'owner' THEN 0 ELSE 1 END, username`,
		workspaceID,
	)
	if err != nil {
		return nil
	}
	defer rows.Close()
	var members []WorkspaceMember
	for rows.Next() {
		var m WorkspaceMember
		rows.Scan(&m.Username, &m.Role, &m.InvitedBy, &m.Status, &m.CanInvite, &m.CanOpen)
		members = append(members, m)
	}
	return members
}

func workspaceMemberPermissions(workspaceID int, username string) (status string, invitedBy string, canInvite bool, canOpen bool, found bool) {
	if strings.TrimSpace(username) == "" {
		return "", "", false, false, false
	}
	status = ""
	invitedBy = ""
	canInvite = false
	canOpen = false
	err := db.QueryRow(
		`SELECT COALESCE(status, 'accepted'), COALESCE(invited_by, ''), COALESCE(can_invite, TRUE), COALESCE(can_open, TRUE)
		 FROM workspace_members WHERE workspace_id = $1 AND username = $2`,
		workspaceID, username,
	).Scan(&status, &invitedBy, &canInvite, &canOpen)
	if err != nil {
		return "", "", false, false, false
	}
	return status, invitedBy, canInvite, canOpen, true
}

func registerHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != "POST" {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var user User
	if err := json.NewDecoder(r.Body).Decode(&user); err != nil {
		http.Error(w, `{"error": "Format JSON tidak valid"}`, http.StatusBadRequest)
		return
	}

	if os.Getenv("REGISTRATION_ENABLED") == "false" {
		http.Error(w, `{"error": "Pendaftaran akun baru sedang dinonaktifkan oleh administrator."}`, http.StatusForbidden)
		return
	}

	user.Username = strings.TrimSpace(user.Username)
	user.Password = strings.TrimSpace(user.Password)

	if len(user.Username) < 3 {
		http.Error(w, `{"error": "Username minimal 3 karakter"}`, http.StatusBadRequest)
		return
	}
	if len(user.Password) < 6 {
		http.Error(w, `{"error": "Password minimal 6 karakter"}`, http.StatusBadRequest)
		return
	}

	_, err := db.Exec(
		"INSERT INTO users (username, password, nama, role) VALUES ($1, $2, $3, 'user')",
		user.Username, user.Password, user.Nama,
	)
	if err != nil {
		if strings.Contains(strings.ToLower(err.Error()), "unique") ||
			strings.Contains(strings.ToLower(err.Error()), "duplicate") {
			http.Error(w, `{"error": "Username sudah digunakan"}`, http.StatusConflict)
			return
		}
		log.Printf("register error: %v", err)
		http.Error(w, `{"error": "Gagal mendaftar"}`, http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.Write([]byte(`{"message": "Daftar berhasil, silakan login"}`))
}

// ================= SHP UPLOAD =================
func uploadSHPHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != "POST" {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	
	err := r.ParseMultipartForm(32 << 20) // 32 MB limit in memory
	if err != nil {
		log.Printf("UPLOAD ERROR: Gagal memproses file: %v", err)
		http.Error(w, "Gagal memproses file: "+err.Error(), http.StatusBadRequest)
		return
	}

	file, header, err := r.FormFile("file")
	if err != nil {
		log.Printf("UPLOAD ERROR: File tidak ditemukan: %v", err)
		http.Error(w, "File tidak ditemukan: "+err.Error(), http.StatusBadRequest)
		return
	}
	defer file.Close()

	datasetName := strings.TrimSuffix(header.Filename, ".zip")
	workspaceID := r.FormValue("workspace_id")
	if workspaceID == "" { workspaceID = "1" } // Fallback

	tableName := fmt.Sprintf("ws%s_data_%d", workspaceID, time.Now().Unix())

	tmpDir, err := os.MkdirTemp("", "shp_*")
	if err != nil {
		log.Printf("UPLOAD ERROR: Gagal membuat temporary directory: %v", err)
		http.Error(w, "Gagal membuat temporary directory: "+err.Error(), http.StatusInternalServerError)
		return
	}
	defer os.RemoveAll(tmpDir)

	zipPath := filepath.Join(tmpDir, header.Filename)
	outZip, err := os.Create(zipPath)
	if err != nil {
		log.Printf("UPLOAD ERROR: Gagal menyimpan zip: %v", err)
		http.Error(w, "Gagal menyimpan zip: "+err.Error(), http.StatusInternalServerError)
		return
	}
	io.Copy(outZip, file)
	outZip.Close()

	// Unzip
	zipReader, err := zip.OpenReader(zipPath)
	if err != nil {
		log.Printf("UPLOAD ERROR: Bukan file zip yang valid: %v", err)
		http.Error(w, "Bukan file zip yang valid: "+err.Error(), http.StatusBadRequest)
		return
	}

	var shpPath string
	for _, f := range zipReader.File {
		fPath := filepath.Join(tmpDir, f.Name)
		if f.FileInfo().IsDir() {
			os.MkdirAll(fPath, os.ModePerm)
			continue
		}
		os.MkdirAll(filepath.Dir(fPath), os.ModePerm)
		outFile, err := os.OpenFile(fPath, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, f.Mode())
		if err != nil {
			continue
		}
		rc, err := f.Open()
		if err != nil {
			outFile.Close()
			continue
		}
		io.Copy(outFile, rc)
		outFile.Close()
		rc.Close()

		if strings.HasSuffix(strings.ToLower(f.Name), ".shp") {
			shpPath = fPath
		}
	}
	zipReader.Close()

	if shpPath == "" {
		log.Printf("UPLOAD ERROR: File .shp tidak ditemukan di dalam zip")
		http.Error(w, "File .shp tidak ditemukan di dalam zip", http.StatusBadRequest)
		return
	}

	pgHost := os.Getenv("DB_HOST")
	if pgHost == "" { pgHost = "localhost" }
	pgPort := os.Getenv("DB_PORT")
	if pgPort == "" { pgPort = "5432" }
	pgUser := os.Getenv("DB_USER")
	if pgUser == "" { pgUser = "gisnas_user" }
	pgPass := os.Getenv("DB_PASSWORD")
	if pgPass == "" { pgPass = "gisnas_password" }
	pgDB := os.Getenv("DB_NAME")
	if pgDB == "" { pgDB = "gisnas_db" }

	pgConnStr := fmt.Sprintf("PG:host=%s port=%s user=%s dbname=%s password='%s'", pgHost, pgPort, pgUser, pgDB, pgPass)

	// ogr2ogr to postgis
	cmd := exec.Command("ogr2ogr",
		"-f", "PostgreSQL",
		pgConnStr,
		shpPath,
		"-nln", tableName,
		"-t_srs", "EPSG:4326",
		"-lco", "GEOMETRY_NAME=geom",
		"-lco", "FID=id",
		"-nlt", "PROMOTE_TO_MULTI",
		"-overwrite",
	)
	
	output, err := cmd.CombinedOutput()
	if err != nil {
		log.Printf("UPLOAD ERROR: Gagal konversi SHP ke PostGIS:\nError: %v\nOutput: %s", err, string(output))
		http.Error(w, "Gagal konversi SHP ke PostGIS: "+err.Error()+"\n"+string(output), http.StatusInternalServerError)
		return
	}

	var geomType string
	err = db.QueryRow("SELECT type FROM geometry_columns WHERE f_table_name = $1", tableName).Scan(&geomType)
	if err != nil {
		geomType = "GEOMETRY"
	}

	db.Exec(fmt.Sprintf("CREATE INDEX ON %s USING GIST(geom);", tableName))
	db.Exec(fmt.Sprintf("ALTER TABLE %s ADD COLUMN create_gn TIMESTAMP DEFAULT CURRENT_TIMESTAMP;", tableName))
	db.Exec(fmt.Sprintf("ALTER TABLE %s ADD COLUMN update_gn TIMESTAMP DEFAULT CURRENT_TIMESTAMP;", tableName))
	db.Exec(fmt.Sprintf(`
		CREATE TRIGGER update_timestamp_trigger
		BEFORE UPDATE ON %s
		FOR EACH ROW
		EXECUTE FUNCTION update_timestamp_column();
	`, tableName))

	_, err = db.Exec("INSERT INTO datasets (workspace_id, name, geom_type, srid, table_name) VALUES ($1, $2, $3, 4326, $4)", workspaceID, datasetName, geomType, tableName)
	if err != nil {
		log.Printf("UPLOAD ERROR: Gagal simpan metadata ke database: %v", err)
		http.Error(w, "Gagal simpan metadata ke database: "+err.Error(), http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.Write([]byte(fmt.Sprintf(`{"message": "File %s berhasil diunggah dengan sempurna!"}`, header.Filename)))
}

// ================= WORKSPACES & DATASETS =================
func getWorkspacesHandler(w http.ResponseWriter, r *http.Request) {
	username := requestUsername(r)
	role := requestRole(r)

	var rows *sql.Rows
	var err error
	if role == "superadmin" || username == "" {
		rows, err = db.Query(`
			SELECT id, name, COALESCE(owner_username, ''), COALESCE(is_collab, false), 'accepted', ''
			FROM workspaces ORDER BY id DESC`)
	} else {
		rows, err = db.Query(`
			SELECT DISTINCT w.id, w.name, COALESCE(w.owner_username, ''), COALESCE(w.is_collab, false),
			       COALESCE(m.status, CASE WHEN w.owner_username = $1 THEN 'accepted' ELSE '' END),
			       COALESCE(m.invited_by, '')
			FROM workspaces w
			LEFT JOIN workspace_members m ON m.workspace_id = w.id AND m.username = $1
			WHERE w.owner_username = $1 OR m.username = $1
			ORDER BY w.id DESC`, username)
	}
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	defer rows.Close()

	var ws []Workspace
	for rows.Next() {
		var wData Workspace
		rows.Scan(&wData.ID, &wData.Name, &wData.OwnerUsername, &wData.IsCollab, &wData.MyStatus, &wData.MyInvitedBy)
		if role == "superadmin" || (wData.OwnerUsername != "" && wData.OwnerUsername == username) {
			wData.CanOpen = true
			wData.CanInvite = true
			wData.MyStatus = "accepted"
		} else {
			_, _, wData.CanInvite, wData.CanOpen, _ = workspaceMemberPermissions(wData.ID, username)
		}
		wData.Members = loadWorkspaceMembers(wData.ID)
		wData.CanManage = workspaceCanManage(wData.OwnerUsername, role, username)
		wData.CanDelete = wData.CanManage
		ws = append(ws, wData)
	}
	if ws == nil {
		ws = []Workspace{}
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(ws)
}

func createWorkspaceHandler(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Name          string `json:"name"`
		OwnerUsername string `json:"owner_username"`
	}
	json.NewDecoder(r.Body).Decode(&body)
	owner := strings.TrimSpace(body.OwnerUsername)
	if owner == "" {
		owner = requestUsername(r)
	}
	if strings.TrimSpace(body.Name) == "" {
		http.Error(w, `{"error": "Nama workspace wajib diisi"}`, http.StatusBadRequest)
		return
	}
	if owner == "" {
		http.Error(w, `{"error": "Username pemilik wajib (login ulang)"}`, http.StatusBadRequest)
		return
	}

	var ws Workspace
	err := db.QueryRow(
		`INSERT INTO workspaces (name, owner_username, is_collab) VALUES ($1, $2, false) RETURNING id`,
		strings.TrimSpace(body.Name), owner,
	).Scan(&ws.ID)
	if err != nil {
		http.Error(w, "Gagal bikin workspace", http.StatusInternalServerError)
		return
	}
	ws.Name = body.Name
	ws.OwnerUsername = owner
	db.Exec(
		`INSERT INTO workspace_members (workspace_id, username, role, invited_by) VALUES ($1, $2, 'owner', $2)
		 ON CONFLICT (workspace_id, username) DO NOTHING`,
		ws.ID, owner,
	)
	ws.Members = loadWorkspaceMembers(ws.ID)
	ws.CanDelete = true
	ws.CanManage = true

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(ws)
}

func listUsersHandler(w http.ResponseWriter, r *http.Request) {
	rows, err := db.Query(`SELECT username FROM users ORDER BY username`)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	defer rows.Close()
	var users []string
	for rows.Next() {
		var u string
		rows.Scan(&u)
		users = append(users, u)
	}
	if users == nil {
		users = []string{}
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(users)
}

// ================= ADMIN USER MANAGEMENT =================
func adminOnlyMiddleware(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		role := requestRole(r)
		if role != "superadmin" {
			http.Error(w, `{"error": "Hanya superadmin yang bisa mengakses ini"}`, http.StatusForbidden)
			return
		}
		next(w, r)
	}
}

func adminListUsersHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != "GET" {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	rows, err := db.Query(`SELECT id, username, COALESCE(nama, ''), role, COALESCE(is_blocked, FALSE), COALESCE(blocked_at::text, ''), COALESCE(created_at::text, '') FROM users ORDER BY id`)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	defer rows.Close()
	type UserInfo struct {
		ID        int    `json:"id"`
		Username  string `json:"username"`
		Nama      string `json:"nama"`
		Role      string `json:"role"`
		IsBlocked bool   `json:"is_blocked"`
		BlockedAt string `json:"blocked_at,omitempty"`
		CreatedAt string `json:"created_at,omitempty"`
	}
	var users []UserInfo
	for rows.Next() {
		var u UserInfo
		rows.Scan(&u.ID, &u.Username, &u.Nama, &u.Role, &u.IsBlocked, &u.BlockedAt, &u.CreatedAt)
		users = append(users, u)
	}
	if users == nil {
		users = []UserInfo{}
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(users)
}

func adminBlockUserHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != "POST" {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var req struct {
		Username string `json:"username"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error": "Format JSON tidak valid"}`, http.StatusBadRequest)
		return
	}
	req.Username = strings.TrimSpace(req.Username)
	if req.Username == "" {
		http.Error(w, `{"error": "Username wajib diisi"}`, http.StatusBadRequest)
		return
	}
	// Cannot block superadmin
	var role string
	db.QueryRow("SELECT role FROM users WHERE username = $1", req.Username).Scan(&role)
	if role == "superadmin" {
		http.Error(w, `{"error": "Tidak bisa memblokir akun superadmin"}`, http.StatusForbidden)
		return
	}
	_, err := db.Exec("UPDATE users SET is_blocked = TRUE, blocked_at = NOW() WHERE username = $1", req.Username)
	if err != nil {
		http.Error(w, `{"error": "Gagal memblokir user"}`, http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.Write([]byte(`{"message": "User berhasil diblokir"}`))
}

func adminUnblockUserHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != "POST" {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var req struct {
		Username string `json:"username"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error": "Format JSON tidak valid"}`, http.StatusBadRequest)
		return
	}
	req.Username = strings.TrimSpace(req.Username)
	if req.Username == "" {
		http.Error(w, `{"error": "Username wajib diisi"}`, http.StatusBadRequest)
		return
	}
	_, err := db.Exec("UPDATE users SET is_blocked = FALSE, blocked_at = NULL WHERE username = $1", req.Username)
	if err != nil {
		http.Error(w, `{"error": "Gagal membuka blokir user"}`, http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.Write([]byte(`{"message": "Blokir user berhasil dibuka"}`))
}

func adminCreateUserHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != "POST" {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var req struct {
		Username string `json:"username"`
		Password string `json:"password"`
		Nama     string `json:"nama"`
		Role     string `json:"role"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error": "Format JSON tidak valid"}`, http.StatusBadRequest)
		return
	}
	req.Username = strings.TrimSpace(req.Username)
	req.Password = strings.TrimSpace(req.Password)
	req.Nama = strings.TrimSpace(req.Nama)
	if len(req.Username) < 3 {
		http.Error(w, `{"error": "Username minimal 3 karakter"}`, http.StatusBadRequest)
		return
	}
	if len(req.Password) < 6 {
		http.Error(w, `{"error": "Password minimal 6 karakter"}`, http.StatusBadRequest)
		return
	}
	if req.Role == "" {
		req.Role = "user"
	}
	_, err := db.Exec("INSERT INTO users (username, password, nama, role) VALUES ($1, $2, $3, $4)", req.Username, req.Password, req.Nama, req.Role)
	if err != nil {
		if strings.Contains(strings.ToLower(err.Error()), "unique") || strings.Contains(strings.ToLower(err.Error()), "duplicate") {
			http.Error(w, `{"error": "Username sudah digunakan"}`, http.StatusConflict)
			return
		}
		http.Error(w, `{"error": "Gagal membuat user"}`, http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.Write([]byte(`{"message": "User berhasil dibuat"}`))
}

func addWorkspaceMemberHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != "POST" {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var req struct {
		WorkspaceID int    `json:"workspace_id"`
		Username    string `json:"username"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error": "Format JSON tidak valid"}`, http.StatusBadRequest)
		return
	}
	invitee := strings.TrimSpace(strings.TrimPrefix(req.Username, "@"))
	actor := requestUsername(r)
	role := requestRole(r)
	if invitee == "" || req.WorkspaceID <= 0 {
		http.Error(w, `{"error": "workspace_id dan username wajib"}`, http.StatusBadRequest)
		return
	}

	var owner string
	err := db.QueryRow(
		`SELECT COALESCE(owner_username, '') FROM workspaces WHERE id = $1`, req.WorkspaceID,
	).Scan(&owner)
	if err != nil {
		http.Error(w, `{"error": "Workspace tidak ditemukan"}`, http.StatusNotFound)
		return
	}
	if !workspaceCanInvite(owner, role, actor, req.WorkspaceID) {
		http.Error(w, `{"error": "Kamu tidak punya izin mengundang user di workspace ini"}`, http.StatusForbidden)
		return
	}

	var exists bool
	db.QueryRow(`SELECT EXISTS(SELECT 1 FROM users WHERE username = $1)`, invitee).Scan(&exists)
	if !exists {
		http.Error(w, `{"error": "User tidak ada"}`, http.StatusNotFound)
		return
	}
	if invitee == actor {
		http.Error(w, `{"error": "Tidak bisa mengundang diri sendiri"}`, http.StatusBadRequest)
		return
	}

	var existingStatus string
	statusErr := db.QueryRow(
		`SELECT COALESCE(status, 'accepted') FROM workspace_members WHERE workspace_id = $1 AND username = $2`,
		req.WorkspaceID, invitee,
	).Scan(&existingStatus)
	if statusErr == nil && existingStatus == "accepted" {
		http.Error(w, `{"error": "User sudah jadi anggota"}`, http.StatusConflict)
		return
	} else if statusErr != nil && statusErr != sql.ErrNoRows {
		http.Error(w, `{"error": "Gagal mengecek status anggota"}`, http.StatusInternalServerError)
		return
	}

	_, err = db.Exec(
		`INSERT INTO workspace_members (workspace_id, username, role, status, invited_by) VALUES ($1, $2, 'editor', 'pending', $3)
		 ON CONFLICT (workspace_id, username) DO UPDATE SET status = 'pending', invited_by = EXCLUDED.invited_by`,
		req.WorkspaceID, invitee, actor,
	)
	if err != nil {
		http.Error(w, `{"error": "Gagal menambah kolaborator"}`, http.StatusInternalServerError)
		return
	}
	refreshWorkspaceCollabFlag(req.WorkspaceID)

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"status":  "success",
		"message": fmt.Sprintf("Undangan dikirim ke @%s. Tunggu konfirmasi user tersebut.", invitee),
		"members": loadWorkspaceMembers(req.WorkspaceID),
	})
}

func respondWorkspaceInvitationHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != "POST" {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req struct {
		WorkspaceID int    `json:"workspace_id"`
		Action      string `json:"action"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error": "Format JSON tidak valid"}`, http.StatusBadRequest)
		return
	}

	username := requestUsername(r)
	action := strings.ToLower(strings.TrimSpace(req.Action))
	if username == "" || req.WorkspaceID <= 0 || (action != "accept" && action != "reject") {
		http.Error(w, `{"error": "workspace_id dan action wajib valid"}`, http.StatusBadRequest)
		return
	}

	var res sql.Result
	var err error
	if action == "accept" {
		res, err = db.Exec(
			`UPDATE workspace_members SET status = 'accepted', can_invite = COALESCE(can_invite, TRUE), can_open = COALESCE(can_open, TRUE)
			 WHERE workspace_id = $1 AND username = $2 AND COALESCE(status, 'accepted') = 'pending'`,
			req.WorkspaceID, username,
		)
	} else {
		res, err = db.Exec(
			`DELETE FROM workspace_members
			 WHERE workspace_id = $1 AND username = $2 AND COALESCE(status, 'accepted') = 'pending'`,
			req.WorkspaceID, username,
		)
	}
	if err != nil {
		http.Error(w, `{"error": "Gagal memproses undangan"}`, http.StatusInternalServerError)
		return
	}
	n, _ := res.RowsAffected()
	if n == 0 {
		http.Error(w, `{"error": "Undangan tidak ditemukan"}`, http.StatusNotFound)
		return
	}

	refreshWorkspaceCollabFlag(req.WorkspaceID)
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"status": "success",
		"action": action,
	})
}

func removeWorkspaceMemberHandler(w http.ResponseWriter, r *http.Request) {
	workspaceID := r.URL.Query().Get("workspace_id")
	username := strings.TrimSpace(strings.TrimPrefix(r.URL.Query().Get("username"), "@"))
	actor := requestUsername(r)
	role := requestRole(r)

	if workspaceID == "" || username == "" {
		http.Error(w, `{"error": "workspace_id dan username wajib"}`, http.StatusBadRequest)
		return
	}

	var owner string
	var wsID int
	err := db.QueryRow(
		`SELECT id, COALESCE(owner_username, '') FROM workspaces WHERE id = $1`, workspaceID,
	).Scan(&wsID, &owner)
	if err != nil {
		http.Error(w, `{"error": "Workspace tidak ditemukan"}`, http.StatusNotFound)
		return
	}
	if username == owner {
		http.Error(w, `{"error": "Pemilik tidak bisa dikeluarkan"}`, http.StatusBadRequest)
		return
	}
	if !workspaceCanManage(owner, role, actor) {
		http.Error(w, `{"error": "Hanya pemilik yang bisa mengeluarkan anggota"}`, http.StatusForbidden)
		return
	}

	db.Exec(`DELETE FROM workspace_members WHERE workspace_id = $1 AND username = $2`, wsID, username)
	refreshWorkspaceCollabFlag(wsID)

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"status":  "success",
		"message": fmt.Sprintf("@%s dikeluarkan dari proyek", username),
	})
}

func updateWorkspaceMemberPermissionsHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != "PATCH" && r.Method != "POST" {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req struct {
		WorkspaceID int    `json:"workspace_id"`
		Username    string `json:"username"`
		CanInvite   bool   `json:"can_invite"`
		CanOpen     bool   `json:"can_open"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error": "Format JSON tidak valid"}`, http.StatusBadRequest)
		return
	}
	req.Username = strings.TrimSpace(strings.TrimPrefix(req.Username, "@"))
	actor := requestUsername(r)
	role := requestRole(r)
	if req.WorkspaceID <= 0 || req.Username == "" {
		http.Error(w, `{"error": "workspace_id dan username wajib"}`, http.StatusBadRequest)
		return
	}

	var owner string
	err := db.QueryRow(`SELECT COALESCE(owner_username, '') FROM workspaces WHERE id = $1`, req.WorkspaceID).Scan(&owner)
	if err != nil {
		http.Error(w, `{"error": "Workspace tidak ditemukan"}`, http.StatusNotFound)
		return
	}
	if !workspaceCanManage(owner, role, actor) {
		http.Error(w, `{"error": "Hanya pembuat workspace yang bisa mengatur izin user"}`, http.StatusForbidden)
		return
	}
	if req.Username == owner {
		http.Error(w, `{"error": "Izin pembuat workspace tidak bisa diubah"}`, http.StatusBadRequest)
		return
	}

	res, err := db.Exec(
		`UPDATE workspace_members SET can_invite = $1, can_open = $2
		 WHERE workspace_id = $3 AND username = $4 AND COALESCE(status, 'accepted') = 'accepted'`,
		req.CanInvite, req.CanOpen, req.WorkspaceID, req.Username,
	)
	if err != nil {
		http.Error(w, `{"error": "Gagal mengubah izin user"}`, http.StatusInternalServerError)
		return
	}
	n, _ := res.RowsAffected()
	if n == 0 {
		http.Error(w, `{"error": "User tidak ditemukan di workspace"}`, http.StatusNotFound)
		return
	}
	refreshWorkspaceCollabFlag(req.WorkspaceID)
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"status":     "success",
		"username":   req.Username,
		"can_invite": req.CanInvite,
		"can_open":   req.CanOpen,
		"members":    loadWorkspaceMembers(req.WorkspaceID),
	})
}

func deleteWorkspaceHandler(w http.ResponseWriter, r *http.Request) {
	id := r.URL.Query().Get("id")
	if id == "" {
		http.Error(w, "ID dibutuhkan", http.StatusBadRequest)
		return
	}

	username := requestUsername(r)
	role := requestRole(r)
	var owner string
	err := db.QueryRow(
		`SELECT COALESCE(owner_username, '') FROM workspaces WHERE id = $1`, id,
	).Scan(&owner)
	if err != nil {
		http.Error(w, `{"error": "Workspace tidak ditemukan"}`, http.StatusNotFound)
		return
	}
	if owner != "" && !workspaceCanManage(owner, role, username) {
		http.Error(w, `{"error": "Hanya @pemilik atau superadmin yang bisa menghapus workspace"}`, http.StatusForbidden)
		return
	}

	// Delete associated records first to avoid foreign key violations
	db.Exec(`DELETE FROM workspace_members WHERE workspace_id = $1`, id)
	_, err = db.Exec("DELETE FROM api_tokens WHERE workspace_id = $1", id)
	if err != nil {
		http.Error(w, "Gagal menghapus token terkait: "+err.Error(), http.StatusInternalServerError)
		return
	}
	_, err = db.Exec("DELETE FROM datasets WHERE workspace_id = $1", id)
	if err != nil {
		http.Error(w, "Gagal menghapus dataset terkait: "+err.Error(), http.StatusInternalServerError)
		return
	}
	_, err = db.Exec("DELETE FROM workspaces WHERE id = $1", id)
	if err != nil {
		http.Error(w, "Gagal menghapus workspace: "+err.Error(), http.StatusInternalServerError)
		return
	}
	
	w.Header().Set("Content-Type", "application/json")
	w.Write([]byte(`{"message": "Workspace terhapus"}`))
}

type ColumnSpec struct {
	Name string `json:"name"`
	Type string `json:"type"`
}

type CreateDatasetReq struct {
	WorkspaceID int          `json:"workspace_id"`
	Name        string       `json:"name"`
	GeomType    string       `json:"geom_type"`
	SRID        int          `json:"srid"`
	Columns     []ColumnSpec `json:"columns"`
}

func createBlankDatasetHandler(w http.ResponseWriter, r *http.Request) {
	var req CreateDatasetReq
	json.NewDecoder(r.Body).Decode(&req)
	if req.SRID == 0 { req.SRID = 4326 }
	
	tableName := fmt.Sprintf("ws%d_data_%d", req.WorkspaceID, time.Now().Unix())
	
	columnsSQL := ""
	for _, col := range req.Columns {
		safeColName := sanitizeIdentifier(col.Name)
		if safeColName == "" {
			continue
		}
		safeType := mapColumnType(col.Type)
		columnsSQL += fmt.Sprintf(", %s %s", safeColName, safeType)
	}

	createTableQuery := fmt.Sprintf(`
		CREATE TABLE %s (
			id SERIAL PRIMARY KEY,
			geom geometry(%s, %d),
			create_gn TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
			update_gn TIMESTAMP DEFAULT CURRENT_TIMESTAMP%s
		);
	`, tableName, req.GeomType, req.SRID, columnsSQL)
	
	_, err := db.Exec(createTableQuery)
	if err != nil {
		http.Error(w, "Gagal bikin tabel spasial: "+err.Error(), http.StatusInternalServerError)
		return
	}

	db.Exec(fmt.Sprintf("CREATE INDEX ON %s USING GIST(geom);", tableName))
	db.Exec(fmt.Sprintf(`
		CREATE TRIGGER update_timestamp_trigger
		BEFORE UPDATE ON %s
		FOR EACH ROW
		EXECUTE FUNCTION update_timestamp_column();
	`, tableName))

	_, err = db.Exec("INSERT INTO datasets (workspace_id, name, geom_type, srid, table_name) VALUES ($1, $2, $3, $4, $5)", req.WorkspaceID, req.Name, req.GeomType, req.SRID, tableName)
	if err != nil {
		http.Error(w, "Gagal catat metadata dataset: "+err.Error(), http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.Write([]byte(fmt.Sprintf(`{"message": "Dokumen %s (EPSG:%d) berhasil dibuat!"}`, req.Name, req.SRID)))
}

func sanitizeIdentifier(s string) string {
	var res []rune
	for _, r := range s {
		if (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') || (r >= '0' && r <= '9') || r == '_' {
			res = append(res, r)
		}
	}
	return string(res)
}

func sqlValueToJSON(val interface{}) interface{} {
	if val == nil {
		return nil
	}
	switch v := val.(type) {
	case []byte:
		return string(v)
	case time.Time:
		return v.Format("2006-01-02 15:04:05")
	default:
		return v
	}
}

func datasetDisplayNameFromRequest(r *http.Request, uploadedFilename string) string {
	if r != nil {
		if n := strings.TrimSpace(r.FormValue("layer_name")); n != "" {
			return n
		}
	}
	if uploadedFilename != "" {
		base := strings.TrimSuffix(filepath.Base(uploadedFilename), filepath.Ext(uploadedFilename))
		if base != "" && !strings.EqualFold(base, "upload") {
			return base
		}
	}
	return fmt.Sprintf("layer_%d", time.Now().Unix())
}

func mapColumnType(rawType string) string {
	rawUpper := strings.TrimSpace(strings.ToUpper(rawType))
	
	if strings.HasPrefix(rawUpper, "VARCHAR") {
		lengthStr := ""
		for _, r := range rawUpper {
			if r >= '0' && r <= '9' {
				lengthStr += string(r)
			}
		}
		if lengthStr != "" {
			return fmt.Sprintf("VARCHAR(%s)", lengthStr)
		}
		return "VARCHAR(255)"
	}
	
	if strings.HasPrefix(rawUpper, "CHAR") {
		lengthStr := ""
		for _, r := range rawUpper {
			if r >= '0' && r <= '9' {
				lengthStr += string(r)
			}
		}
		if lengthStr != "" {
			return fmt.Sprintf("CHAR(%s)", lengthStr)
		}
		return "CHAR(1)"
	}

	switch rawUpper {
	case "INTEGER", "INT", "INT4", "LONG INTEGER":
		return "INTEGER"
	case "SMALLINT", "INT2", "SHORT INTEGER":
		return "SMALLINT"
	case "BIGINT", "INT8", "BIG INTEGER":
		return "BIGINT"
	case "REAL", "FLOAT", "FLOAT4":
		return "REAL"
	case "DOUBLE", "DOUBLE PRECISION", "FLOAT8":
		return "DOUBLE PRECISION"
	case "DATE":
		return "DATE"
	case "TIMESTAMP":
		return "TIMESTAMP"
	case "TIMESTAMP WITH TIME ZONE", "TIMESTAMPTZ":
		return "TIMESTAMPTZ"
	case "BOOLEAN", "BOOL":
		return "BOOLEAN"
	case "UUID", "GUID":
		return "UUID"
	case "TEXT":
		return "TEXT"
	default:
		return "TEXT"
	}
}

func getDatasetsHandler(w http.ResponseWriter, r *http.Request) {
	workspaceID := r.URL.Query().Get("workspace_id")
	if workspaceID == "" {
		http.Error(w, "workspace_id dibutuhkan", http.StatusBadRequest)
		return
	}

	rows, err := db.Query(`
		SELECT d.id, d.workspace_id, d.name, d.geom_type, d.srid, COALESCE(d.table_name, ''),
		       COALESCE(s.fill_color, '#3b82f6'), COALESCE(s.stroke_color, '#ffffff')
		FROM datasets d
		LEFT JOIN stylings s ON d.id = s.dataset_id
		WHERE d.workspace_id = $1
		ORDER BY d.id DESC
	`, workspaceID)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	defer rows.Close()

	var datasets []Dataset
	for rows.Next() {
		var d Dataset
		err := rows.Scan(&d.ID, &d.WorkspaceID, &d.Name, &d.GeomType, &d.SRID, &d.TableName, &d.FillColor, &d.StrokeColor)
		if err != nil {
			continue
		}
		
		// Query BBox
		d.BBox = []float64{118.0, -2.5, 118.0, -2.5} // default center point
		if d.TableName != "" {
			var xmin, ymin, xmax, ymax sql.NullFloat64
			bboxQuery := fmt.Sprintf("SELECT ST_XMin(ext::geometry), ST_YMin(ext::geometry), ST_XMax(ext::geometry), ST_YMax(ext::geometry) FROM (SELECT ST_Extent(ST_Transform(geom, 4326)) as ext FROM %s) sub", d.TableName)
			err := db.QueryRow(bboxQuery).Scan(&xmin, &ymin, &xmax, &ymax)
			if err == nil && xmin.Valid && ymin.Valid && xmax.Valid && ymax.Valid {
				d.BBox = []float64{xmin.Float64, ymin.Float64, xmax.Float64, ymax.Float64}
			}
		}

		datasets = append(datasets, d)
	}
	if datasets == nil { datasets = []Dataset{} }

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(datasets)
}

func getDatasetDataHandler(w http.ResponseWriter, r *http.Request) {
	datasetID := r.URL.Query().Get("dataset_id")
	if datasetID == "" {
		http.Error(w, "dataset_id dibutuhkan", http.StatusBadRequest)
		return
	}

	var tableName string
	err := db.QueryRow("SELECT COALESCE(table_name, '') FROM datasets WHERE id = $1", datasetID).Scan(&tableName)
	if err != nil || tableName == "" {
		http.Error(w, "Dataset tidak ditemukan", http.StatusNotFound)
		return
	}

	safeTable := sanitizeIdentifier(tableName)
	if safeTable == "" {
		http.Error(w, "Nama tabel tidak valid", http.StatusBadRequest)
		return
	}

	colRows, err := db.Query(`
		SELECT column_name 
		FROM information_schema.columns 
		WHERE table_schema = 'public' AND table_name = $1 AND column_name != 'geom'
		ORDER BY ordinal_position
	`, tableName)
	if err != nil {
		http.Error(w, "Gagal baca skema kolom: "+err.Error(), http.StatusInternalServerError)
		return
	}
	defer colRows.Close()

	var columns []string
	for colRows.Next() {
		var colName string
		colRows.Scan(&colName)
		columns = append(columns, colName)
	}

	selectCols := []string{"ST_AsText(ST_Transform(geom, 4326)) as geom_wkt"}
	for _, c := range columns {
		selectCols = append(selectCols, fmt.Sprintf(`"%s"`, sanitizeIdentifier(c)))
	}

	query := fmt.Sprintf("SELECT %s FROM %s ORDER BY id ASC LIMIT 500", strings.Join(selectCols, ", "), safeTable)
	rows, err := db.Query(query)
	if err != nil {
		log.Printf("dataset data query error: %v (table=%s)", err, safeTable)
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`[]`))
		return
	}
	defer rows.Close()

	cols, _ := rows.Columns()
	var resultList []map[string]interface{}

	for rows.Next() {
		columnsPointers := make([]interface{}, len(cols))
		columnValues := make([]interface{}, len(cols))
		for i := range columnValues {
			columnsPointers[i] = &columnValues[i]
		}

		if err := rows.Scan(columnsPointers...); err != nil {
			continue
		}

		rowMap := make(map[string]interface{})
		for i, colName := range cols {
			rowMap[colName] = sqlValueToJSON(columnValues[i])
		}
		resultList = append(resultList, rowMap)
	}
	if resultList == nil { resultList = []map[string]interface{}{} }

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(resultList)
}

func getDatasetSchemaHandler(w http.ResponseWriter, r *http.Request) {
	datasetID := r.URL.Query().Get("dataset_id")
	if datasetID == "" {
		http.Error(w, "dataset_id dibutuhkan", http.StatusBadRequest)
		return
	}

	var tableName string
	err := db.QueryRow("SELECT COALESCE(table_name, '') FROM datasets WHERE id = $1", datasetID).Scan(&tableName)
	if err != nil || tableName == "" {
		http.Error(w, "Dataset tidak ditemukan", http.StatusNotFound)
		return
	}

	colRows, err := db.Query(`
		SELECT column_name, data_type 
		FROM information_schema.columns 
		WHERE table_schema = 'public' AND table_name = $1 AND column_name != 'geom'
		ORDER BY ordinal_position
	`, tableName)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	defer colRows.Close()

	type ColSchema struct {
		Name string `json:"name"`
		Type string `json:"type"`
	}
	var schema []ColSchema
	for colRows.Next() {
		var name, dataType string
		colRows.Scan(&name, &dataType)
		schema = append(schema, ColSchema{Name: name, Type: dataType})
	}
	if schema == nil { schema = []ColSchema{} }

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(schema)
}

func renameDatasetHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != "PATCH" && r.Method != "POST" {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var req struct {
		DatasetID int    `json:"dataset_id"`
		Name      string `json:"name"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error": "Format JSON tidak valid"}`, http.StatusBadRequest)
		return
	}
	name := strings.TrimSpace(req.Name)
	if name == "" || req.DatasetID <= 0 {
		http.Error(w, `{"error": "dataset_id dan name wajib diisi"}`, http.StatusBadRequest)
		return
	}
	res, err := db.Exec("UPDATE datasets SET name = $1 WHERE id = $2", name, req.DatasetID)
	if err != nil {
		http.Error(w, `{"error": "Gagal mengganti nama layer"}`, http.StatusInternalServerError)
		return
	}
	n, _ := res.RowsAffected()
	if n == 0 {
		http.Error(w, `{"error": "Dataset tidak ditemukan"}`, http.StatusNotFound)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"status": "success",
		"name":   name,
	})
}

func deleteDatasetHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != "DELETE" && r.Method != "POST" {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	datasetID := r.URL.Query().Get("dataset_id")
	if datasetID == "" {
		var req struct {
			DatasetID int `json:"dataset_id"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err == nil && req.DatasetID > 0 {
			datasetID = strconv.Itoa(req.DatasetID)
		}
	}
	if datasetID == "" {
		http.Error(w, `{"error": "dataset_id wajib diisi"}`, http.StatusBadRequest)
		return
	}
	var tableName string
	err := db.QueryRow("SELECT COALESCE(table_name, '') FROM datasets WHERE id = $1", datasetID).Scan(&tableName)
	if err != nil || tableName == "" {
		http.Error(w, `{"error": "Dataset tidak ditemukan"}`, http.StatusNotFound)
		return
	}
	safeTable := sanitizeIdentifier(tableName)
	if safeTable == "" {
		http.Error(w, `{"error": "Nama tabel tidak valid"}`, http.StatusBadRequest)
		return
	}
	if _, err := db.Exec(fmt.Sprintf("DROP TABLE IF EXISTS %s CASCADE", safeTable)); err != nil {
		http.Error(w, fmt.Sprintf(`{"error": "Gagal menghapus tabel: %s"}`, err.Error()), http.StatusInternalServerError)
		return
	}
	db.Exec("DELETE FROM stylings WHERE dataset_id = $1", datasetID)
	db.Exec("DELETE FROM datasets WHERE id = $1", datasetID)
	clearTileCache(tableName)
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"status":  "success",
		"message": "Layer berhasil dihapus",
	})
}

func insertDatasetRowHandler(w http.ResponseWriter, r *http.Request) {
	type InsertReq struct {
		DatasetID  int                    `json:"dataset_id"`
		GeomWKT    string                 `json:"geom_wkt"`
		Attributes map[string]interface{} `json:"attributes"`
	}
	var req InsertReq
	json.NewDecoder(r.Body).Decode(&req)

	var tableName string
	var srid int
	err := db.QueryRow("SELECT COALESCE(table_name, ''), srid FROM datasets WHERE id = $1", req.DatasetID).Scan(&tableName, &srid)
	if err != nil || tableName == "" {
		http.Error(w, "Dataset tidak valid", http.StatusBadRequest)
		return
	}

	cols := []string{"geom"}
	vals := []interface{}{req.GeomWKT, srid}
	placeholders := []string{"ST_GeomFromText($1, $2)"}

	paramIdx := 3
	for k, v := range req.Attributes {
		safeK := sanitizeIdentifier(k)
		if safeK == "" || safeK == "geom" || safeK == "id" {
			continue
		}
		cols = append(cols, safeK)
		placeholders = append(placeholders, fmt.Sprintf("$%d", paramIdx))
		vals = append(vals, v)
		paramIdx++
	}

	query := fmt.Sprintf("INSERT INTO %s (%s) VALUES (%s)", tableName, strings.Join(cols, ", "), strings.Join(placeholders, ", "))
	_, err = db.Exec(query, vals...)
	if err != nil {
		http.Error(w, "Gagal insert data: "+err.Error(), http.StatusInternalServerError)
		return
	}
	clearTileCache(tableName)

	w.Header().Set("Content-Type", "application/json")
	w.Write([]byte(`{"message": "Data spasial berhasil ditambahkan!"}`))
}

func addDatasetColumnHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != "POST" {
		http.Error(w, "Method tidak diizinkan", http.StatusMethodNotAllowed)
		return
	}

	type AddColumnReq struct {
		DatasetID  int    `json:"dataset_id"`
		ColumnName string `json:"column_name"`
		ColumnType string `json:"column_type"`
	}

	var req AddColumnReq
	err := json.NewDecoder(r.Body).Decode(&req)
	if err != nil {
		http.Error(w, "Format JSON tidak valid", http.StatusBadRequest)
		return
	}

	safeColName := sanitizeIdentifier(req.ColumnName)
	if safeColName == "" || safeColName == "geom" || safeColName == "id" {
		http.Error(w, "Nama kolom tidak valid", http.StatusBadRequest)
		return
	}

	var tableName string
	err = db.QueryRow("SELECT COALESCE(table_name, '') FROM datasets WHERE id = $1", req.DatasetID).Scan(&tableName)
	if err != nil || tableName == "" {
		http.Error(w, "Dataset tidak ditemukan", http.StatusNotFound)
		return
	}

	safeType := mapColumnType(req.ColumnType)

	query := fmt.Sprintf("ALTER TABLE %s ADD COLUMN %s %s", tableName, safeColName, safeType)
	_, err = db.Exec(query)
	if err != nil {
		http.Error(w, "Gagal menambahkan kolom ke database: "+err.Error(), http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.Write([]byte(`{"message": "Kolom berhasil ditambahkan ke database!"}`))
}
var (
	tileCache      = make(map[string][]byte)
	tileCacheMutex sync.Mutex
)

func clearTileCache(tableName string) {
	tileCacheMutex.Lock()
	defer tileCacheMutex.Unlock()
	prefix := tableName + "/"
	for k := range tileCache {
		if strings.HasPrefix(k, prefix) {
			delete(tileCache, k)
		}
	}
}

func getStylingHandler(w http.ResponseWriter, r *http.Request) {
	datasetID := r.URL.Query().Get("dataset_id")
	if datasetID == "" {
		http.Error(w, "dataset_id dibutuhkan", http.StatusBadRequest)
		return
	}
	
	var s Styling
	err := db.QueryRow("SELECT dataset_id, fill_color, stroke_color FROM stylings WHERE dataset_id = $1", datasetID).Scan(&s.DatasetID, &s.FillColor, &s.StrokeColor)
	if err == sql.ErrNoRows {
		s = Styling{
			DatasetID:   0,
			FillColor:   "#3b82f6",
			StrokeColor: "#ffffff",
		}
	} else if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(s)
}

func saveStylingHandler(w http.ResponseWriter, r *http.Request) {
	var s Styling
	err := json.NewDecoder(r.Body).Decode(&s)
	if err != nil {
		http.Error(w, "JSON tidak valid", http.StatusBadRequest)
		return
	}
	
	var exists bool
	err = db.QueryRow("SELECT EXISTS(SELECT 1 FROM stylings WHERE dataset_id = $1)", s.DatasetID).Scan(&exists)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	
	if exists {
		_, err = db.Exec("UPDATE stylings SET fill_color = $1, stroke_color = $2 WHERE dataset_id = $3", s.FillColor, s.StrokeColor, s.DatasetID)
	} else {
		_, err = db.Exec("INSERT INTO stylings (dataset_id, fill_color, stroke_color) VALUES ($1, $2, $3)", s.DatasetID, s.FillColor, s.StrokeColor)
	}
	if err != nil {
		http.Error(w, "Gagal simpan styling: "+err.Error(), http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.Write([]byte(`{"message": "Styling MapLibre berhasil disimpan secara permanen di Database!"}`))
}

func mvtTileHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Access-Control-Allow-Origin", "*")

	path := strings.TrimPrefix(r.URL.Path, "/api/tiles/")
	path = strings.TrimSuffix(path, ".pbf")
	parts := strings.Split(path, "/")
	if len(parts) < 4 {
		http.Error(w, "Path tidak valid", http.StatusBadRequest)
		return
	}

	tableName := parts[0]
	z, errZ := strconv.Atoi(parts[1])
	x, errX := strconv.Atoi(parts[2])
	y, errY := strconv.Atoi(parts[3])
	if errZ != nil || errX != nil || errY != nil {
		http.Error(w, "Koordinat tile tidak valid", http.StatusBadRequest)
		return
	}

	cacheKey := fmt.Sprintf("%s/%d/%d/%d", tableName, z, x, y)
	tileCacheMutex.Lock()
	cachedTile, found := tileCache[cacheKey]
	tileCacheMutex.Unlock()
	if found {
		w.Header().Set("Content-Type", "application/x-protobuf")
		w.Header().Set("Cache-Control", "public, max-age=3600")
		w.Write(cachedTile)
		return
	}

	var srid int
	err := db.QueryRow("SELECT COALESCE(srid, 4326) FROM datasets WHERE table_name = $1", tableName).Scan(&srid)
	if err == sql.ErrNoRows {
		http.Error(w, "Tabel tidak ditemukan", http.StatusNotFound)
		return
	} else if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	colRows, err := db.Query(`
		SELECT column_name 
		FROM information_schema.columns 
		WHERE table_name = $1 AND column_name != 'geom'
	`, tableName)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	defer colRows.Close()

	var columns []string
	for colRows.Next() {
		var colName string
		colRows.Scan(&colName)
		columns = append(columns, colName)
	}

	var quotedCols []string
	for _, c := range columns {
		quotedCols = append(quotedCols, fmt.Sprintf(`"%s"`, c))
	}
	selectCols := strings.Join(quotedCols, ", ")
	if selectCols != "" {
		selectCols += ", "
	}

	query := fmt.Sprintf(`
		SELECT ST_AsMVT(mvt_geom, $1) FROM (
			SELECT %s ST_AsMVTGeom(ST_Transform(geom, 3857), ST_TileEnvelope($2, $3, $4), 4096, 64, true) AS geom
			FROM %s
			WHERE geom && ST_Transform(ST_TileEnvelope($2, $3, $4), %d)
		) AS mvt_geom
	`, selectCols, tableName, srid)

	var tileData []byte
	err = db.QueryRow(query, tableName, z, x, y).Scan(&tileData)
	if err != nil {
		log.Printf("MVT ERROR: %v (Query: %s)", err, query)
		http.Error(w, "Gagal generate MVT: "+err.Error(), http.StatusInternalServerError)
		return
	}

	tileCacheMutex.Lock()
	tileCache[cacheKey] = tileData
	tileCacheMutex.Unlock()

	w.Header().Set("Content-Type", "application/x-protobuf")
	w.Header().Set("Cache-Control", "public, max-age=3600")
	w.Write(tileData)
}

func deleteDatasetRowHandler(w http.ResponseWriter, r *http.Request) {
	datasetID := r.URL.Query().Get("dataset_id")
	rowID := r.URL.Query().Get("row_id")
	if datasetID == "" || rowID == "" {
		http.Error(w, "dataset_id dan row_id dibutuhkan", http.StatusBadRequest)
		return
	}

	var tableName string
	err := db.QueryRow("SELECT COALESCE(table_name, '') FROM datasets WHERE id = $1", datasetID).Scan(&tableName)
	if err != nil || tableName == "" {
		http.Error(w, "Dataset tidak ditemukan", http.StatusNotFound)
		return
	}

	query := fmt.Sprintf("DELETE FROM %s WHERE id = $1", tableName)
	_, err = db.Exec(query, rowID)
	if err != nil {
		http.Error(w, "Gagal menghapus baris: "+err.Error(), http.StatusInternalServerError)
		return
	}
	clearTileCache(tableName)

	w.Header().Set("Content-Type", "application/json")
	w.Write([]byte(`{"message": "Baris berhasil dihapus!"}`))
}

func updateDatasetRowHandler(w http.ResponseWriter, r *http.Request) {
	type UpdateReq struct {
		DatasetID  int                    `json:"dataset_id"`
		RowID      int                    `json:"row_id"`
		GeomWKT    string                 `json:"geom_wkt"`
		Attributes map[string]interface{} `json:"attributes"`
	}
	var req UpdateReq
	json.NewDecoder(r.Body).Decode(&req)

	var tableName string
	var srid int
	err := db.QueryRow("SELECT COALESCE(table_name, ''), srid FROM datasets WHERE id = $1", req.DatasetID).Scan(&tableName, &srid)
	if err != nil || tableName == "" {
		http.Error(w, "Dataset tidak valid", http.StatusBadRequest)
		return
	}

	setClauses := []string{"geom = ST_GeomFromText($1, $2)"}
	vals := []interface{}{req.GeomWKT, srid}
	paramIdx := 3

	for k, v := range req.Attributes {
		safeK := sanitizeIdentifier(k)
		if safeK == "" || safeK == "geom" || safeK == "id" {
			continue
		}
		setClauses = append(setClauses, fmt.Sprintf("%s = $%d", safeK, paramIdx))
		vals = append(vals, v)
		paramIdx++
	}

	vals = append(vals, req.RowID)
	query := fmt.Sprintf("UPDATE %s SET %s WHERE id = $%d", tableName, strings.Join(setClauses, ", "), paramIdx)
	_, err = db.Exec(query, vals...)
	if err != nil {
		http.Error(w, "Gagal update data: "+err.Error(), http.StatusInternalServerError)
		return
	}
	clearTileCache(tableName)

	w.Header().Set("Content-Type", "application/json")
	w.Write([]byte(`{"message": "Data spasial berhasil diperbarui!"}`))
}

// ================= TOKENS =================
func listTokensHandler(w http.ResponseWriter, r *http.Request) {
	workspaceID := r.URL.Query().Get("workspace_id")
	if workspaceID == "" {
		workspaceID = "0"
	}
	rows, err := db.Query("SELECT id, token_string, workspace_id, status, created_at FROM api_tokens WHERE workspace_id = $1 ORDER BY id DESC", workspaceID)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	defer rows.Close()
	var tokens []Token
	for rows.Next() {
		var t Token
		var wsID sql.NullInt64
		rows.Scan(&t.ID, &t.TokenStr, &wsID, &t.Status, &t.CreatedAt)
		if wsID.Valid {
			t.WorkspaceID = int(wsID.Int64)
		}
		tokens = append(tokens, t)
	}
	if tokens == nil { tokens = []Token{} }
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(tokens)
}

func toggleTokenHandler(w http.ResponseWriter, r *http.Request) {
	tokenStr := r.URL.Query().Get("token")
	if strings.TrimSpace(tokenStr) == "" {
		http.Error(w, `{"error": "token required"}`, http.StatusBadRequest)
		return
	}
	var currentStatus string
	if err := db.QueryRow("SELECT status FROM api_tokens WHERE token_string = $1", tokenStr).Scan(&currentStatus); err != nil {
		http.Error(w, `{"error": "Token tidak ditemukan"}`, http.StatusNotFound)
		return
	}
	newStatus := "STOPPED"
	if currentStatus == "STOPPED" { newStatus = "RUNNING" }
	if _, err := db.Exec("UPDATE api_tokens SET status = $1 WHERE token_string = $2", newStatus, tokenStr); err != nil {
		http.Error(w, `{"error": "Gagal update status token"}`, http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.Write([]byte(`{"message": "Status updated"}`))
}

func generateTokenHandler(w http.ResponseWriter, r *http.Request) {
	workspaceID := r.URL.Query().Get("workspace_id")
	if workspaceID == "" {
		http.Error(w, `{"error": "workspace_id required"}`, http.StatusBadRequest)
		return
	}
	b := make([]byte, 12)
	if _, err := rand.Read(b); err != nil {
		http.Error(w, `{"error": "Failed to generate secure token"}`, http.StatusInternalServerError)
		return
	}
	newToken := "GISNAS-" + hex.EncodeToString(b)
	db.Exec("INSERT INTO api_tokens (token_string, workspace_id) VALUES ($1, $2)", newToken, workspaceID)
	w.Header().Set("Content-Type", "application/json")
	w.Write([]byte(`{"message": "Token dibuat"}`))
}

func deleteTokenHandler(w http.ResponseWriter, r *http.Request) {
	tokenStr := r.URL.Query().Get("token")
	db.Exec("DELETE FROM api_tokens WHERE token_string = $1", tokenStr)
	w.Header().Set("Content-Type", "application/json")
	w.Write([]byte(`{"message": "Token dihapus"}`))
}

// ================= OGC API FEATURES (WITH TOKEN MIDDLEWARE) =================
func ogcMiddleware(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		token := r.URL.Query().Get("token")
		if token == "" {
			parts := strings.Split(r.URL.Path, "/")
			for i, part := range parts {
				if part == "token" && i+1 < len(parts) {
					token = parts[i+1]
					break
				}
			}
		}
		if token == "" {
			http.Error(w, `{"error": "Token tidak ditemukan. Akses QGIS ditolak."}`, http.StatusUnauthorized)
			return
		}

		var status string
		var wsID sql.NullInt64
		err := db.QueryRow("SELECT status, workspace_id FROM api_tokens WHERE token_string = $1", token).Scan(&status, &wsID)
		if err != nil {
			http.Error(w, `{"error": "Token tidak valid."}`, http.StatusUnauthorized)
			return
		}

		if status == "STOPPED" {
			http.Error(w, `{"error": "Token telah di-STOP. Akses QGIS diblokir."}`, http.StatusForbidden)
			return
		}

		if wsID.Valid {
			q := r.URL.Query()
			q.Set("token_workspace_id", fmt.Sprintf("%d", wsID.Int64))
			r.URL.RawQuery = q.Encode()
		}

		next.ServeHTTP(w, r)
	}
}


func ogcUploadGPKGHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != "POST" {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	
	err := r.ParseMultipartForm(128 << 20) // 128 MB limit
	if err != nil {
		http.Error(w, "Gagal memproses file: "+err.Error(), http.StatusBadRequest)
		return
	}

	file, header, err := r.FormFile("file")
	if err != nil {
		http.Error(w, "File tidak ditemukan: "+err.Error(), http.StatusBadRequest)
		return
	}
	defer file.Close()

	workspaceID := r.URL.Query().Get("token_workspace_id")
	if workspaceID == "" { workspaceID = "1" }

	tableName := fmt.Sprintf("ws%s_data_%d", workspaceID, time.Now().Unix())

	tmpDir, err := os.MkdirTemp("", "gpkg_*")
	if err != nil {
		http.Error(w, "Gagal membuat temporary directory", http.StatusInternalServerError)
		return
	}
	defer os.RemoveAll(tmpDir)

	gpkgPath := filepath.Join(tmpDir, header.Filename)
	outGpkg, err := os.Create(gpkgPath)
	if err != nil {
		http.Error(w, "Gagal menyimpan gpkg", http.StatusInternalServerError)
		return
	}
	io.Copy(outGpkg, file)
	outGpkg.Close()

	pgHost := os.Getenv("DB_HOST")
	if pgHost == "" { pgHost = "localhost" }
	pgPort := os.Getenv("DB_PORT")
	if pgPort == "" { pgPort = "5432" }
	pgUser := os.Getenv("DB_USER")
	if pgUser == "" { pgUser = "gisnas_user" }
	pgPass := os.Getenv("DB_PASSWORD")
	if pgPass == "" { pgPass = "gisnas_password" }
	pgDB := os.Getenv("DB_NAME")
	if pgDB == "" { pgDB = "gisnas_db" }

	pgConnStr := fmt.Sprintf("PG:host=%s port=%s user=%s dbname=%s password='%s'", pgHost, pgPort, pgUser, pgDB, pgPass)

	cmd := exec.Command("ogr2ogr", "-f", "PostgreSQL", pgConnStr, gpkgPath, "-nln", tableName, "-t_srs", "EPSG:4326", "-lco", "GEOMETRY_NAME=geom", "-lco", "FID=id", "-nlt", "PROMOTE_TO_MULTI", "-overwrite")
	
	output, err := cmd.CombinedOutput()
	if err != nil {
		http.Error(w, "Gagal konversi GPKG ke PostGIS: "+string(output), http.StatusInternalServerError)
		return
	}

	var geomType string
	err = db.QueryRow("SELECT type FROM geometry_columns WHERE f_table_name = $1", tableName).Scan(&geomType)
	if err != nil {
		geomType = "GEOMETRY"
	}

	db.Exec(fmt.Sprintf("CREATE INDEX ON %s USING GIST(geom);", tableName))

	var featureCount int
	db.QueryRow(fmt.Sprintf("SELECT COUNT(*) FROM %s", tableName)).Scan(&featureCount)

	displayName := datasetDisplayNameFromRequest(r, header.Filename)

	db.Exec("INSERT INTO datasets (workspace_id, name, geom_type, srid, table_name) VALUES ($1, $2, $3, 4326, $4)",
		workspaceID, displayName, geomType, tableName)

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"message":       "Upload berhasil",
		"name":          displayName,
		"table_name":    tableName,
		"feature_count": featureCount,
	})
}

func ogcDownloadGPKGHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != "GET" {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	tableName := r.URL.Query().Get("table_name")
	if tableName == "" {
		http.Error(w, "table_name dibutuhkan", http.StatusBadRequest)
		return
	}

	workspaceID := r.URL.Query().Get("token_workspace_id")
	var exists bool
	err := db.QueryRow("SELECT EXISTS(SELECT 1 FROM datasets WHERE table_name = $1 AND workspace_id = $2)", tableName, workspaceID).Scan(&exists)
	if err != nil || !exists {
		http.Error(w, "Tabel tidak ditemukan", http.StatusNotFound)
		return
	}

	tmpDir, err := os.MkdirTemp("", "gpkg_down_*")
	if err != nil {
		http.Error(w, "Gagal membuat temp dir", http.StatusInternalServerError)
		return
	}
	
	go func() {
		time.Sleep(5 * time.Minute)
		os.RemoveAll(tmpDir)
	}()

	gpkgPath := filepath.Join(tmpDir, tableName+".gpkg")

	pgHost := os.Getenv("DB_HOST")
	if pgHost == "" { pgHost = "localhost" }
	pgPort := os.Getenv("DB_PORT")
	if pgPort == "" { pgPort = "5432" }
	pgUser := os.Getenv("DB_USER")
	if pgUser == "" { pgUser = "gisnas_user" }
	pgPass := os.Getenv("DB_PASSWORD")
	if pgPass == "" { pgPass = "gisnas_password" }
	pgDB := os.Getenv("DB_NAME")
	if pgDB == "" { pgDB = "gisnas_db" }

	pgConnStr := fmt.Sprintf("PG:host=%s port=%s user=%s dbname=%s password='%s'", pgHost, pgPort, pgUser, pgDB, pgPass)

	// FID=fid: GPKG pakai kolom fid (lokal); id tetap atribut server (sesuai gisnas_sketsa)
	cmd := exec.Command("ogr2ogr", "-f", "GPKG", gpkgPath, pgConnStr, tableName, "-lco", "FID=fid")
	output, err := cmd.CombinedOutput()
	if err != nil {
		http.Error(w, "Gagal ekspor ke GPKG: "+string(output), http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Disposition", fmt.Sprintf("attachment; filename=\"%s.gpkg\"", tableName))
	w.Header().Set("Content-Type", "application/geopackage+sqlite3")
	http.ServeFile(w, r, gpkgPath)
}

func getOldFeatureAsJSON(tableName string, featureID string) (geomJSON string, propsJSON string) {
	colRows, err := db.Query(fmt.Sprintf(`SELECT column_name FROM information_schema.columns WHERE table_name = '%s' AND column_name NOT IN ('geom', 'create_gn', 'update_gn') ORDER BY ordinal_position`, tableName))
	if err != nil { return "", "{}" }
	defer colRows.Close()
	var columns []string
	for colRows.Next() {
		var cName string
		colRows.Scan(&cName)
		columns = append(columns, cName)
	}
	selectCols := []string{"ST_AsGeoJSON(ST_Transform(geom, 4326)) as geom_geojson"}
	for _, c := range columns { selectCols = append(selectCols, fmt.Sprintf(`"%s"`, c)) }
	row := db.QueryRow(fmt.Sprintf("SELECT %s FROM %s WHERE id = $1", strings.Join(selectCols, ", "), tableName), featureID)
	columnsPointers := make([]interface{}, len(selectCols))
	columnValues := make([]interface{}, len(selectCols))
	for i := range columnValues { columnsPointers[i] = &columnValues[i] }
	if err := row.Scan(columnsPointers...); err != nil { return "", "{}" }
	properties := make(map[string]interface{})
	var geomRaw string
	for i, colName := range selectCols {
		val := columnValues[i]
		if colName == "geom_geojson" {
			if val != nil {
				switch v := val.(type) {
				case []byte: geomRaw = string(v)
				case string: geomRaw = v
				default: geomRaw = fmt.Sprintf("%s", val)
				}
			}
		} else {
			cleanName := strings.Trim(colName, `"`)
			if cleanName == "id" { continue }
			if val != nil {
				switch v := val.(type) {
				case []byte: properties[cleanName] = string(v)
				case string: properties[cleanName] = v
				default: properties[cleanName] = val
				}
			}
		}
	}
	propsBytes, _ := json.Marshal(properties)
	return geomRaw, string(propsBytes)
}

func ogcHistoryHandler(w http.ResponseWriter, r *http.Request, tableName string) {
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Content-Type", "application/json")
	
	rows, err := db.Query("SELECT id, feature_id, action, COALESCE(old_geom::text, '{}'), COALESCE(new_geom::text, '{}'), COALESCE(old_properties::text, '{}'), COALESCE(new_properties::text, '{}'), changed_by, created_at FROM feature_history WHERE table_name = $1 ORDER BY created_at DESC", tableName)
	if err != nil {
		http.Error(w, `{"error": "Failed to fetch history"}`, http.StatusInternalServerError)
		return
	}
	defer rows.Close()
	
	var history []map[string]interface{}
	for rows.Next() {
		var id, featureId int
		var action, oldGeomStr, newGeomStr, oldPropsStr, newPropsStr, changedBy string
		var createdAt time.Time
		rows.Scan(&id, &featureId, &action, &oldGeomStr, &newGeomStr, &oldPropsStr, &newPropsStr, &changedBy, &createdAt)
		
		var oldGeom, newGeom, oldProps, newProps interface{}
		json.Unmarshal([]byte(oldGeomStr), &oldGeom)
		json.Unmarshal([]byte(newGeomStr), &newGeom)
		json.Unmarshal([]byte(oldPropsStr), &oldProps)
		json.Unmarshal([]byte(newPropsStr), &newProps)
		
		history = append(history, map[string]interface{}{
			"id": id,
			"feature_id": featureId,
			"action": action,
			"old_geom": oldGeom,
			"new_geom": newGeom,
			"old_properties": oldProps,
			"new_properties": newProps,
			"changed_by": changedBy,
			"created_at": createdAt,
		})
	}
	
	if history == nil {
		history = []map[string]interface{}{}
	}
	
	json.NewEncoder(w).Encode(history)
}

func ogcFeaturesCRUDHandler(w http.ResponseWriter, r *http.Request) {
	// Disable caching for all OGC API Features endpoints to prevent QGIS from caching stale schemas
	w.Header().Set("Cache-Control", "no-cache, no-store, must-revalidate")
	w.Header().Set("Pragma", "no-cache")
	w.Header().Set("Expires", "0")

	path := r.URL.Path
	token := r.URL.Query().Get("token")

	if strings.HasPrefix(path, "/token/") {
		parts := strings.Split(path, "/")
		if len(parts) >= 3 {
			if token == "" {
				token = parts[2]
			}
			path = "/" + strings.Join(parts[3:], "/")
		}
	} else {
		trimmedPath := strings.TrimPrefix(path, "/api/ogc/features")
		trimmedPath = strings.Trim(trimmedPath, "/")
		if strings.HasPrefix(trimmedPath, "token/") {
			parts := strings.Split(trimmedPath, "/")
			if len(parts) >= 2 {
				if token == "" {
					token = parts[1]
				}
				path = "/api/ogc/features/" + strings.Join(parts[2:], "/")
			}
		}
	}

	path = strings.TrimPrefix(path, "/api/ogc/features")
	path = strings.Trim(path, "/")

	// Determine absolute base URL for strict GIS clients (e.g. QGIS)
	scheme := "http"
	if r.Header.Get("X-Forwarded-Proto") != "" {
		scheme = r.Header.Get("X-Forwarded-Proto")
	} else if r.TLS != nil {
		scheme = "https"
	}
	baseURL := fmt.Sprintf("%s://%s", scheme, r.Host)

	if path == "upload_gpkg" {
		ogcUploadGPKGHandler(w, r)
		return
	}
	if path == "download_gpkg" {
		ogcDownloadGPKGHandler(w, r)
		return
	}

	if path == "" {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(fmt.Sprintf(`{
			"title": "GISNAS OGC API Features Service",
			"description": "Direct bypass to PostGIS for QGIS",
			"links": [
				{ "href": "%s/token/%s/api/ogc/features/?token=%s", "rel": "self", "type": "application/json" },
				{ "href": "%s/token/%s/api/ogc/features/collections?token=%s", "rel": "data", "type": "application/json" },
				{ "href": "%s/token/%s/api/ogc/features/conformance?token=%s", "rel": "conformance", "type": "application/json" },
				{ "href": "%s/token/%s/api/ogc/features/api?token=%s", "rel": "service-desc", "type": "application/vnd.oai.openapi+json;version=3.0" }
			]
		}`, baseURL, token, token, baseURL, token, token, baseURL, token, token, baseURL, token, token)))
		return
	}

	if path == "api" {
		w.Header().Set("Content-Type", "application/vnd.oai.openapi+json;version=3.0")
		w.Write([]byte(`{
			"openapi": "3.0.0",
			"info": {
				"title": "GISNAS OGC API Features Service",
				"version": "1.0.0"
			},
			"paths": {
				"/": {
					"get": {
						"summary": "Landing Page",
						"operationId": "getLandingPage",
						"responses": {
							"200": { "description": "Landing Page" }
						}
					}
				},
				"/conformance": {
					"get": {
						"summary": "Conformance Classes",
						"operationId": "getConformance",
						"responses": {
							"200": { "description": "Conformance declaration" }
						}
					}
				},
				"/collections": {
					"get": {
						"summary": "Collections Metadata",
						"operationId": "getCollections",
						"responses": {
							"200": { "description": "Collections metadata" }
						}
					}
				},
				"/collections/{collectionId}": {
					"get": {
						"summary": "Collection Metadata",
						"operationId": "getCollection",
						"responses": {
							"200": { "description": "Collection metadata" }
						}
					}
				},
				"/collections/{collectionId}/items": {
					"get": {
						"summary": "Get Features",
						"operationId": "getFeatures",
						"responses": {
							"200": { "description": "Features in collection" }
						}
					},
					"post": {
						"summary": "Create Feature",
						"operationId": "createFeature",
						"responses": {
							"201": { "description": "Feature created successfully" }
						}
					}
				},
				"/collections/{collectionId}/items/{featureId}": {
					"get": {
						"summary": "Get Single Feature",
						"operationId": "getFeature",
						"responses": {
							"200": { "description": "Single feature" }
						}
					},
					"put": {
						"summary": "Replace Feature",
						"operationId": "replaceFeature",
						"responses": {
							"204": { "description": "Feature replaced successfully" }
						}
					},
					"patch": {
						"summary": "Update Feature",
						"operationId": "updateFeature",
						"responses": {
							"204": { "description": "Feature updated successfully" }
						}
					},
					"delete": {
						"summary": "Delete Feature",
						"operationId": "deleteFeature",
						"responses": {
							"204": { "description": "Feature deleted successfully" }
						}
					}
				}
			}
		}`))
		return
	}

	if path == "conformance" {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{
			"conformsTo": [
				"http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core",
				"http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/oas30",
				"http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson",
				"http://www.opengis.net/spec/ogcapi-features-4/1.0/conf/create-replace-delete",
				"http://www.opengis.net/spec/ogcapi-features-4/1.0/conf/update",
				"http://www.opengis.net/spec/ogcapi-features-4/1.0/conf/features",
				"http://www.opengis.net/spec/ogcapi-features-4/1.0/conf/simple-transactions"
			]
		}`))
		return
	}

	if path == "collections" {
		wsID := r.URL.Query().Get("token_workspace_id")

		if r.Method == "POST" {
			w.Header().Set("Content-Type", "application/json")
			var req CreateDatasetReq
			if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
				http.Error(w, `{"error": "Format JSON tidak valid"}`, http.StatusBadRequest)
				return
			}
			
			if req.SRID == 0 { req.SRID = 4326 }
			if req.WorkspaceID == 0 {
				wsIDInt, _ := strconv.Atoi(wsID)
				req.WorkspaceID = wsIDInt
			}
			if req.WorkspaceID == 0 { req.WorkspaceID = 1 } // Fallback
			
			tableName := fmt.Sprintf("ws%d_data_%d", req.WorkspaceID, time.Now().Unix())
			
			columnsSQL := ""
			for _, col := range req.Columns {
				safeColName := sanitizeIdentifier(col.Name)
				if safeColName == "" || safeColName == "geom" || safeColName == "id" {
					continue
				}
				safeType := mapColumnType(col.Type)
				columnsSQL += fmt.Sprintf(", %s %s", safeColName, safeType)
			}

			createTableQuery := fmt.Sprintf(`
				CREATE TABLE %s (
					id SERIAL PRIMARY KEY,
					geom geometry(%s, %d),
					create_gn TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
					update_gn TIMESTAMP DEFAULT CURRENT_TIMESTAMP%s
				);
			`, tableName, req.GeomType, req.SRID, columnsSQL)
			
			_, err := db.Exec(createTableQuery)
			if err != nil {
				http.Error(w, fmt.Sprintf(`{"error": "Gagal bikin tabel spasial: %s"}`, err.Error()), http.StatusInternalServerError)
				return
			}

			db.Exec(fmt.Sprintf("CREATE INDEX ON %s USING GIST(geom);", tableName))
			db.Exec(fmt.Sprintf(`
				CREATE TRIGGER update_timestamp_trigger
				BEFORE UPDATE ON %s
				FOR EACH ROW
				EXECUTE FUNCTION update_timestamp_column();
			`, tableName))

			_, err = db.Exec("INSERT INTO datasets (workspace_id, name, geom_type, srid, table_name) VALUES ($1, $2, $3, $4, $5)", req.WorkspaceID, req.Name, req.GeomType, req.SRID, tableName)
			if err != nil {
				http.Error(w, fmt.Sprintf(`{"error": "Gagal catat metadata dataset: %s"}`, err.Error()), http.StatusInternalServerError)
				return
			}
			
			json.NewEncoder(w).Encode(map[string]interface{}{
				"status": "success",
				"table_name": tableName,
				"message": fmt.Sprintf("Koleksi %s berhasil dibuat", req.Name),
			})
			return
		}

		w.Header().Set("Content-Type", "application/json")
		query := "SELECT id, name, geom_type, srid, COALESCE(table_name, '') FROM datasets"
		var rows *sql.Rows
		var err error
		if wsID != "" {
			query += " WHERE workspace_id = $1"
			rows, err = db.Query(query, wsID)
		} else {
			rows, err = db.Query(query)
		}
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		defer rows.Close()


		type Extent struct {
			Spatial map[string]interface{} `json:"spatial"`
		}
		type Collection struct {
			ID          string           `json:"id"`
			Title       string           `json:"title"`
			Description string           `json:"description"`
			ItemType    string           `json:"itemType"`
			Extent      Extent           `json:"extent"`
			Links       []CollectionLink `json:"links"`
		}

		var collections []Collection
		for rows.Next() {
			var id int
			var name, geomType, tableName string
			var srid int
			rows.Scan(&id, &name, &geomType, &srid, &tableName)
			if tableName == "" {
				continue
			}

			links := []CollectionLink{
				{Href: fmt.Sprintf("%s/token/%s/api/ogc/features/collections/%s?token=%s", baseURL, token, tableName, token), Rel: "self", Type: "application/json"},
				{Href: fmt.Sprintf("%s/token/%s/api/ogc/features/collections/%s/items?token=%s", baseURL, token, tableName, token), Rel: "items", Type: "application/geo+json"},
				{Href: fmt.Sprintf("%s/token/%s/api/ogc/features/collections/%s/queryables?token=%s", baseURL, token, tableName, token), Rel: "http://www.opengis.net/def/rel/ogc/1.0/queryables", Type: "application/schema+json"},
			}
			collections = append(collections, Collection{
				ID:          tableName,
				Title:       name,
				Description: fmt.Sprintf("PostGIS Layer: %s (%s)", name, geomType),
				ItemType:    "feature",
				Extent: Extent{
					Spatial: map[string]interface{}{
						"bbox": [][]float64{{-180, -90, 180, 90}},
					},
				},
				Links: links,
			})
		}
		if collections == nil { collections = []Collection{} }


		json.NewEncoder(w).Encode(map[string]interface{}{
			"collections": collections,
			"links": []CollectionLink{
				{Href: fmt.Sprintf("%s/token/%s/api/ogc/features/collections?token=%s", baseURL, token, token), Rel: "self", Type: "application/json"},
			},
		})
		return
	}

	parts := strings.Split(path, "/")
	if len(parts) >= 2 && parts[0] == "collections" {
		tableName := parts[1]

		wsID := r.URL.Query().Get("token_workspace_id")
		var dsID int
		var dsName, geomType string
		var srid int
		var err error
		if wsID != "" {
			err = db.QueryRow("SELECT id, name, geom_type, srid FROM datasets WHERE table_name = $1 AND workspace_id = $2", tableName, wsID).Scan(&dsID, &dsName, &geomType, &srid)
		} else {
			err = db.QueryRow("SELECT id, name, geom_type, srid FROM datasets WHERE table_name = $1", tableName).Scan(&dsID, &dsName, &geomType, &srid)
		}
		if err != nil {
			http.Error(w, "Layer/Tabel tidak ditemukan", http.StatusNotFound)
			return
		}

		if len(parts) == 2 {
			if r.Method == "OPTIONS" {
				w.Header().Set("Allow", "GET, PATCH, DELETE, OPTIONS")
				w.WriteHeader(http.StatusOK)
				return
			}

			if r.Method == "PATCH" {
				w.Header().Set("Content-Type", "application/json")
				var body struct {
					Title string `json:"title"`
				}
				if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
					http.Error(w, `{"error": "Format JSON tidak valid"}`, http.StatusBadRequest)
					return
				}
				newName := strings.TrimSpace(body.Title)
				if newName == "" {
					http.Error(w, `{"error": "title wajib diisi"}`, http.StatusBadRequest)
					return
				}
				if wsID != "" {
					_, err = db.Exec("UPDATE datasets SET name = $1 WHERE table_name = $2 AND workspace_id = $3", newName, tableName, wsID)
				} else {
					_, err = db.Exec("UPDATE datasets SET name = $1 WHERE table_name = $2", newName, tableName)
				}
				if err != nil {
					http.Error(w, fmt.Sprintf(`{"error": "Gagal rename: %s"}`, err.Error()), http.StatusInternalServerError)
					return
				}
				dsName = newName
				json.NewEncoder(w).Encode(map[string]interface{}{
					"id":    tableName,
					"title": newName,
					"status": "success",
				})
				return
			}

			if r.Method == "DELETE" {
				w.Header().Set("Content-Type", "application/json")
				safeTable := sanitizeIdentifier(tableName)
				if safeTable == "" {
					http.Error(w, `{"error": "Nama tabel tidak valid"}`, http.StatusBadRequest)
					return
				}
				_, err := db.Exec(fmt.Sprintf("DROP TABLE IF EXISTS %s CASCADE", safeTable))
				if err != nil {
					http.Error(w, fmt.Sprintf(`{"error": "Gagal menghapus tabel: %s"}`, err.Error()), http.StatusInternalServerError)
					return
				}
				if wsID != "" {
					db.Exec("DELETE FROM datasets WHERE table_name = $1 AND workspace_id = $2", tableName, wsID)
				} else {
					db.Exec("DELETE FROM datasets WHERE table_name = $1", tableName)
				}
				clearTileCache(tableName)
				w.WriteHeader(http.StatusOK)
				w.Write([]byte(`{"status": "success", "message": "Layer berhasil dihapus"}`))
				return
			}

			if r.Method != "GET" {
				http.Error(w, "Method tidak diizinkan", http.StatusMethodNotAllowed)
				return
			}

			w.Header().Set("Content-Type", "application/json")

			type Extent struct {
				Spatial map[string]interface{} `json:"spatial"`
			}
			json.NewEncoder(w).Encode(map[string]interface{}{
				"id":          tableName,
				"title":       dsName,
				"description": fmt.Sprintf("PostGIS Layer: %s (%s)", dsName, geomType),
				"itemType":    "feature",
				"extent": Extent{
					Spatial: map[string]interface{}{
						"bbox": [][]float64{{-180, -90, 180, 90}},
					},
				},
				"links": []CollectionLink{
					{Href: fmt.Sprintf("%s/token/%s/api/ogc/features/collections/%s?token=%s", baseURL, token, tableName, token), Rel: "self", Type: "application/json"},
					{Href: fmt.Sprintf("%s/token/%s/api/ogc/features/collections/%s/items?token=%s", baseURL, token, tableName, token), Rel: "items", Type: "application/geo+json"},
					{Href: fmt.Sprintf("%s/token/%s/api/ogc/features/collections/%s/queryables?token=%s", baseURL, token, tableName, token), Rel: "http://www.opengis.net/def/rel/ogc/1.0/queryables", Type: "application/schema+json"},
				},
			})
			return
		}

		if len(parts) == 3 && parts[2] == "history" {
			ogcHistoryHandler(w, r, tableName)
			return
		}

		if len(parts) == 3 && parts[2] == "columns" {
			if r.Method == "OPTIONS" {
				w.Header().Set("Allow", "GET, POST, DELETE, OPTIONS")
				w.WriteHeader(http.StatusOK)
				return
			}
			
			if r.Method == "GET" {
				w.Header().Set("Content-Type", "application/json")
				colRows, err := db.Query(`
					SELECT column_name, data_type 
					FROM information_schema.columns 
					WHERE table_name = $1 AND column_name != 'geom'
					ORDER BY ordinal_position
				`, tableName)
				if err != nil {
					http.Error(w, `{"error": "Gagal membaca skema"}`, http.StatusInternalServerError)
					return
				}
				defer colRows.Close()

				type ColInfo struct {
					Name string `json:"name"`
					Type string `json:"type"`
				}
				var columns []ColInfo
				for colRows.Next() {
					var cName, cType string
					colRows.Scan(&cName, &cType)
					columns = append(columns, ColInfo{Name: cName, Type: cType})
				}
				if columns == nil { columns = []ColInfo{} }
				json.NewEncoder(w).Encode(columns)
				return
			}
			
			if r.Method == "POST" {
				w.Header().Set("Content-Type", "application/json")
				type AddColumnReq struct {
					ColumnName string `json:"column_name"`
					ColumnType string `json:"column_type"`
				}

				var req AddColumnReq
				err := json.NewDecoder(r.Body).Decode(&req)
				if err != nil {
					http.Error(w, `{"error": "Format JSON tidak valid"}`, http.StatusBadRequest)
					return
				}

				safeColName := sanitizeIdentifier(req.ColumnName)
				if safeColName == "" || safeColName == "geom" || safeColName == "id" {
					http.Error(w, `{"error": "Nama kolom tidak valid"}`, http.StatusBadRequest)
					return
				}

				safeType := mapColumnType(req.ColumnType)

				query := fmt.Sprintf("ALTER TABLE %s ADD COLUMN %s %s", tableName, safeColName, safeType)
				_, err = db.Exec(query)
				if err != nil {
					http.Error(w, fmt.Sprintf(`{"error": "Gagal menambahkan kolom ke database: %s"}`, err.Error()), http.StatusInternalServerError)
					return
				}

				clearTileCache(tableName)

				w.WriteHeader(http.StatusOK)
				w.Write([]byte(`{"status": "success", "message": "Kolom berhasil ditambahkan!"}`))
				return
			}

			if r.Method == "DELETE" {
				w.Header().Set("Content-Type", "application/json")
				colName := r.URL.Query().Get("name")
				safeColName := sanitizeIdentifier(colName)
				if safeColName == "" || safeColName == "geom" || safeColName == "id" {
					http.Error(w, `{"error": "Nama kolom tidak valid"}`, http.StatusBadRequest)
					return
				}

				query := fmt.Sprintf("ALTER TABLE %s DROP COLUMN %s", tableName, safeColName)
				_, err = db.Exec(query)
				if err != nil {
					http.Error(w, fmt.Sprintf(`{"error": "Gagal menghapus kolom dari database: %s"}`, err.Error()), http.StatusInternalServerError)
					return
				}

				clearTileCache(tableName)

				w.WriteHeader(http.StatusOK)
				w.Write([]byte(`{"status": "success", "message": "Kolom berhasil dihapus!"}`))
				return
			}
			
			http.Error(w, "Method tidak diizinkan", http.StatusMethodNotAllowed)
			return
		}

		// OGC API Part 3: Queryables – returns JSON Schema of the collection's properties.
		// QGIS reads this endpoint to discover the field schema of a collection.
		if len(parts) == 3 && parts[2] == "queryables" {
			w.Header().Set("Content-Type", "application/schema+json")
			// Map PostgreSQL data_type to JSON Schema types
			pgToJSONSchema := func(pgType string) map[string]interface{} {
				pgUpper := strings.ToUpper(pgType)
				switch {
				case strings.Contains(pgUpper, "INT"):
					return map[string]interface{}{"type": "integer"}
				case strings.Contains(pgUpper, "REAL") || strings.Contains(pgUpper, "DOUBLE") || strings.Contains(pgUpper, "NUMERIC") || strings.Contains(pgUpper, "FLOAT"):
					return map[string]interface{}{"type": "number"}
				case strings.Contains(pgUpper, "BOOL"):
					return map[string]interface{}{"type": "boolean"}
				case strings.Contains(pgUpper, "DATE") && !strings.Contains(pgUpper, "TIMESTAMP"):
					return map[string]interface{}{"type": "string", "format": "date"}
				case strings.Contains(pgUpper, "TIMESTAMP"):
					return map[string]interface{}{"type": "string", "format": "date-time"}
				default:
					return map[string]interface{}{"type": "string"}
				}
			}

			colRows, err := db.Query(`
				SELECT column_name, data_type 
				FROM information_schema.columns 
				WHERE table_name = $1 AND column_name != 'geom'
				ORDER BY ordinal_position
			`, tableName)
			if err != nil {
				http.Error(w, `{"error": "Gagal membaca skema"}`, http.StatusInternalServerError)
				return
			}
			defer colRows.Close()

			properties := map[string]interface{}{
				"geometry": map[string]interface{}{
					"$ref": "https://geojson.org/schema/Geometry.json",
					"x-ogc-role": "primary-geometry",
				},
			}
			required := []string{}
			for colRows.Next() {
				var cName, cType string
				colRows.Scan(&cName, &cType)
				propDef := pgToJSONSchema(cType)
				propDef["title"] = cName
				propDef["x-ogc-property-seq"] = len(properties)
				properties[cName] = propDef
				if cName == "id" {
					required = append(required, cName)
				}
			}

			queryable := map[string]interface{}{
				"$schema":     "https://json-schema.org/draft/2019-09/schema",
				"$id":         fmt.Sprintf("%s/token/%s/api/ogc/features/collections/%s/queryables?token=%s", baseURL, token, tableName, token),
				"type":        "object",
				"title":       dsName,
				"description": fmt.Sprintf("Queryable properties for %s", dsName),
				"properties":  properties,
				"required":    required,
			}

			json.NewEncoder(w).Encode(queryable)
			return
		}

		if len(parts) == 3 && parts[2] == "items" {
			if r.Method == "OPTIONS" {
				w.Header().Set("Allow", "GET, HEAD, POST, OPTIONS")
				w.WriteHeader(http.StatusOK)
				return
			}

			if r.Method == "POST" {
				w.Header().Set("Content-Type", "application/json")
				var body struct {
					Type       string                 `json:"type"`
					Geometry   interface{}            `json:"geometry"`
					Properties map[string]interface{} `json:"properties"`
				}
				if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
					http.Error(w, `{"error": "Format JSON tidak valid"}`, http.StatusBadRequest)
					return
				}

				geomBytes, err := json.Marshal(body.Geometry)
				if err != nil {
					http.Error(w, `{"error": "Format geometry salah"}`, http.StatusBadRequest)
					return
				}

				colRows, err := db.Query(`
					SELECT column_name 
					FROM information_schema.columns 
					WHERE table_name = $1 AND column_name NOT IN ('geom', 'id', 'create_gn', 'update_gn')
				`, tableName)
				if err != nil {
					http.Error(w, `{"error": "Gagal membaca skema"}`, http.StatusInternalServerError)
					return
				}
				defer colRows.Close()

				var columns []string
				for colRows.Next() {
					var cName string
					colRows.Scan(&cName)
					columns = append(columns, cName)
				}

				var cols []string
				var vals []interface{}
				var placeholders []string

				cols = append(cols, "geom")
				placeholders = append(placeholders, fmt.Sprintf("ST_SetSRID(ST_GeomFromGeoJSON($1), %d)", srid))
				vals = append(vals, string(geomBytes))

				cleanProps := make(map[string]interface{})
				for k, v := range body.Properties {
					cleanProps[sanitizeIdentifier(k)] = v
				}
				body.Properties = cleanProps

				pCount := 1
				for _, col := range columns {
					if val, ok := body.Properties[col]; ok {
						pCount++
						cols = append(cols, fmt.Sprintf(`"%s"`, col))
						placeholders = append(placeholders, fmt.Sprintf("$%d", pCount))
						vals = append(vals, val)
					}
				}

				query := fmt.Sprintf("INSERT INTO %s (%s) VALUES (%s) RETURNING id", tableName, strings.Join(cols, ", "), strings.Join(placeholders, ", "))
				var newID int
				err = db.QueryRow(query, vals...).Scan(&newID)
				if err != nil {
					http.Error(w, fmt.Sprintf(`{"error": "Gagal insert: %s"}`, err.Error()), http.StatusInternalServerError)
					return
				}
				clearTileCache(tableName)
				
				propsBytes, _ := json.Marshal(body.Properties)
				if geomBytesStr := string(geomBytes); geomBytesStr != "null" {
					db.Exec("INSERT INTO feature_history (table_name, feature_id, action, new_geom, new_properties, changed_by) VALUES ($1, $2, 'INSERT', $3, $4, $5)", tableName, newID, geomBytesStr, string(propsBytes), token)
				}

				loc := fmt.Sprintf("%s/token/%s/api/ogc/features/collections/%s/items/%d?token=%s", baseURL, token, tableName, newID, token)
				w.Header().Set("Location", loc)
				w.WriteHeader(http.StatusCreated)
				json.NewEncoder(w).Encode(map[string]interface{}{
					"id":      newID,
					"status":  "success",
					"message": "Feature berhasil dibuat",
				})
				return
			}

			if r.Method == "GET" || r.Method == "HEAD" {
				w.Header().Set("Content-Type", "application/geo+json")
				colRows, err := db.Query(`
					SELECT column_name 
					FROM information_schema.columns 
					WHERE table_name = $1 AND column_name NOT IN ('geom', 'create_gn', 'update_gn')
					ORDER BY ordinal_position
				`, tableName)
				if err != nil {
					http.Error(w, "Tabel tidak ditemukan", http.StatusNotFound)
					return
				}
				defer colRows.Close()

				var columns []string
				for colRows.Next() {
					var colName string
					colRows.Scan(&colName)
					columns = append(columns, colName)
				}

				selectCols := []string{"ST_AsGeoJSON(ST_Transform(geom, 4326)) as geom_geojson"}
				for _, c := range columns {
					selectCols = append(selectCols, fmt.Sprintf(`"%s"`, c))
				}

				limitStr := r.URL.Query().Get("limit")
				offsetStr := r.URL.Query().Get("offset")
				limit := 1000
				offset := 0
				if limitStr != "" {
					l, err := strconv.Atoi(limitStr)
					if err == nil {
						limit = l
					}
				}
				if offsetStr != "" {
					o, err := strconv.Atoi(offsetStr)
					if err == nil {
						offset = o
					}
				}
				limitClause := ""
				if limit >= 0 {
					limitClause = fmt.Sprintf(" LIMIT %d OFFSET %d", limit, offset)
				}

				query := fmt.Sprintf("SELECT %s FROM %s ORDER BY id ASC%s", strings.Join(selectCols, ", "), tableName, limitClause)
				rows, err := db.Query(query)
				if err != nil {
					log.Printf("OGC GET ITEMS ERROR: %v (Query: %s)", err, query)
					http.Error(w, "Gagal query data spasial: "+err.Error(), http.StatusInternalServerError)
					return
				}
				defer rows.Close()

				type GeoJSONFeature struct {
					Type       string                 `json:"type"`
					Geometry   interface{}            `json:"geometry"`
					Properties map[string]interface{} `json:"properties"`
					ID         interface{}            `json:"id"`
				}

				var features []GeoJSONFeature
				cols, _ := rows.Columns()

				for rows.Next() {
					columnsPointers := make([]interface{}, len(cols))
					columnValues := make([]interface{}, len(cols))
					for i := range columnValues {
						columnsPointers[i] = &columnValues[i]
					}

					if err := rows.Scan(columnsPointers...); err != nil {
						continue
					}

					properties := make(map[string]interface{})
					var geomRaw string
					var rowID interface{}

					for i, colName := range cols {
						val := columnValues[i]
						if colName == "geom_geojson" {
							if val == nil {
								continue
							}
							var strVal string
							isStrOrBytes := false
							switch v := val.(type) {
							case []byte:
								strVal = string(v)
								isStrOrBytes = true
							case string:
								strVal = v
								isStrOrBytes = true
							}
							if isStrOrBytes {
								geomRaw = strVal
							} else {
								geomRaw = fmt.Sprintf("%s", val)
							}
						} else if colName == "id" {
							if val == nil {
								continue
							}
							var strVal string
							isStrOrBytes := false
							switch v := val.(type) {
							case []byte:
								strVal = string(v)
								isStrOrBytes = true
							case string:
								strVal = v
								isStrOrBytes = true
							}
							rowID = val
							if isStrOrBytes {
								rowID = strVal
							}
						} else {
							if val == nil {
								properties[colName] = nil
							} else {
								var strVal string
								isStrOrBytes := false
								switch v := val.(type) {
								case []byte:
									strVal = string(v)
									isStrOrBytes = true
								case string:
									strVal = v
									isStrOrBytes = true
								}
								if isStrOrBytes {
									properties[colName] = strVal
								} else {
									properties[colName] = val
								}
							}
						}
					}

					var geomObj interface{}
					json.Unmarshal([]byte(geomRaw), &geomObj)

					features = append(features, GeoJSONFeature{
						Type:       "Feature",
						Geometry:   geomObj,
						Properties: properties,
						ID:         rowID,
					})
				}
				if features == nil { features = []GeoJSONFeature{} }


				json.NewEncoder(w).Encode(map[string]interface{}{
					"type":           "FeatureCollection",
					"numberMatched":  len(features),
					"numberReturned": len(features),
					"features":       features,
					"links": []CollectionLink{
						{Href: fmt.Sprintf("%s/token/%s/api/ogc/features/collections/%s/items?token=%s", baseURL, token, tableName, token), Rel: "self", Type: "application/geo+json"},
					},
				})
				return
			}
		}

		if len(parts) == 4 && parts[2] == "topology" {
			topoName := fmt.Sprintf("%s_topo", tableName)
			
			if parts[3] == "build" && r.Method == "POST" {
				// Initialize schema
				db.Exec(fmt.Sprintf("SELECT CreateTopology('%s', %d, 0.001)", topoName, srid))
				
				// Populate based on geomType
				upperGeom := strings.ToUpper(geomType)
				if strings.Contains(upperGeom, "LINE") {
					db.Exec(fmt.Sprintf("SELECT TopoGeo_AddLineString('%s', geom, 0.001) FROM %s WHERE geom IS NOT NULL", topoName, tableName))
				} else if strings.Contains(upperGeom, "POINT") {
					db.Exec(fmt.Sprintf("SELECT TopoGeo_AddPoint('%s', geom, 0.001) FROM %s WHERE geom IS NOT NULL", topoName, tableName))
				} else {
					db.Exec(fmt.Sprintf("SELECT TopoGeo_AddPolygon('%s', geom, 0.001) FROM %s WHERE geom IS NOT NULL", topoName, tableName))
				}
				
				// Get counts
				var nodes, edges, faces int
				db.QueryRow(fmt.Sprintf("SELECT COUNT(*) FROM %s.node", topoName)).Scan(&nodes)
				db.QueryRow(fmt.Sprintf("SELECT COUNT(*) FROM %s.edge_data", topoName)).Scan(&edges)
				db.QueryRow(fmt.Sprintf("SELECT COUNT(*) FROM %s.face", topoName)).Scan(&faces)
				
				w.Header().Set("Content-Type", "application/json")
				json.NewEncoder(w).Encode(map[string]interface{}{
					"status": "success",
					"nodes":  nodes,
					"edges":  edges,
					"faces":  faces,
				})
				return
			}

			if parts[3] == "validate" && r.Method == "POST" {
				rows, err := db.Query(fmt.Sprintf("SELECT error FROM ValidateTopology('%s')", topoName))
				if err != nil {
					w.Header().Set("Content-Type", "application/json")
					w.Write([]byte(`{"valid": false, "errors": ["Topology belum di-build"]}`))
					return
				}
				defer rows.Close()
				
				var errorsList []string
				for rows.Next() {
					var errStr string
					if err := rows.Scan(&errStr); err == nil {
						errorsList = append(errorsList, errStr)
					}
				}
				
				if errorsList == nil {
					errorsList = []string{}
				}
				
				w.Header().Set("Content-Type", "application/json")
				json.NewEncoder(w).Encode(map[string]interface{}{
					"valid":  len(errorsList) == 0,
					"errors": errorsList,
				})
				return
			}

			if parts[3] == "stats" && r.Method == "GET" {
				var nodes, edges, faces int
				err := db.QueryRow(fmt.Sprintf("SELECT COUNT(*) FROM %s.node", topoName)).Scan(&nodes)
				if err != nil {
					w.Header().Set("Content-Type", "application/json")
					w.Write([]byte(`{"has_topology": false}`))
					return
				}
				db.QueryRow(fmt.Sprintf("SELECT COUNT(*) FROM %s.edge_data", topoName)).Scan(&edges)
				db.QueryRow(fmt.Sprintf("SELECT COUNT(*) FROM %s.face", topoName)).Scan(&faces)
				
				w.Header().Set("Content-Type", "application/json")
				json.NewEncoder(w).Encode(map[string]interface{}{
					"has_topology": true,
					"nodes":        nodes,
					"edges":        edges,
					"faces":        faces,
				})
				return
			}
		}

		if len(parts) == 4 && parts[2] == "items" {
			featureID := parts[3]

			if r.Method == "OPTIONS" {
				w.Header().Set("Allow", "GET, HEAD, PUT, PATCH, DELETE, OPTIONS")
				w.WriteHeader(http.StatusOK)
				return
			}

			colRows, err := db.Query(`
				SELECT column_name 
				FROM information_schema.columns 
				WHERE table_name = $1 AND column_name NOT IN ('geom', 'create_gn', 'update_gn')
				ORDER BY ordinal_position
			`, tableName)
			if err != nil {
				http.Error(w, `{"error": "Tabel tidak ditemukan"}`, http.StatusNotFound)
				return
			}
			defer colRows.Close()

			var columns []string
			for colRows.Next() {
				var cName string
				colRows.Scan(&cName)
				columns = append(columns, cName)
			}

			if r.Method == "GET" || r.Method == "HEAD" {
				w.Header().Set("Content-Type", "application/geo+json")
				selectCols := []string{"ST_AsGeoJSON(ST_Transform(geom, 4326)) as geom_geojson"}
				selectCols = append(selectCols, columns...)

				query := fmt.Sprintf("SELECT %s FROM %s WHERE id = $1", strings.Join(selectCols, ", "), tableName)
				row := db.QueryRow(query, featureID)

				cols := selectCols
				columnsPointers := make([]interface{}, len(cols))
				columnValues := make([]interface{}, len(cols))
				for i := range columnValues {
					columnsPointers[i] = &columnValues[i]
				}

				if err := row.Scan(columnsPointers...); err != nil {
					http.Error(w, `{"error": "Feature tidak ditemukan"}`, http.StatusNotFound)
					return
				}

				properties := make(map[string]interface{})
				var geomRaw string
				var rowID interface{}

				for i, colName := range cols {
					val := columnValues[i]
					if colName == "geom_geojson" {
						if val == nil {
							continue
						}
						var strVal string
						isStrOrBytes := false
						switch v := val.(type) {
						case []byte:
							strVal = string(v)
							isStrOrBytes = true
						case string:
							strVal = v
							isStrOrBytes = true
						}
						if isStrOrBytes {
							geomRaw = strVal
						} else {
							geomRaw = fmt.Sprintf("%s", val)
						}
					} else if colName == "id" {
						if val == nil {
							continue
						}
						var strVal string
						isStrOrBytes := false
						switch v := val.(type) {
						case []byte:
							strVal = string(v)
							isStrOrBytes = true
						case string:
							strVal = v
							isStrOrBytes = true
						}
						rowID = val
						if isStrOrBytes {
							rowID = strVal
						}
					} else {
						if val == nil {
							properties[colName] = nil
						} else {
							var strVal string
							isStrOrBytes := false
							switch v := val.(type) {
							case []byte:
								strVal = string(v)
								isStrOrBytes = true
							case string:
								strVal = v
								isStrOrBytes = true
							}
							if isStrOrBytes {
								properties[colName] = strVal
							} else {
								properties[colName] = val
							}
						}
					}
				}

				var geomObj interface{}
				json.Unmarshal([]byte(geomRaw), &geomObj)

				json.NewEncoder(w).Encode(map[string]interface{}{
					"type":       "Feature",
					"geometry":   geomObj,
					"properties": properties,
					"id":         rowID,
				})
				return
			}

			if r.Method == "DELETE" {
				w.Header().Set("Content-Type", "application/json")
				
				oldGeom, oldProps := getOldFeatureAsJSON(tableName, featureID)
				
				res, err := db.Exec(fmt.Sprintf("DELETE FROM %s WHERE id = $1", tableName), featureID)
				if err != nil {
					http.Error(w, fmt.Sprintf(`{"error": "Gagal delete: %s"}`, err.Error()), http.StatusInternalServerError)
					return
				}
				rowsAffected, _ := res.RowsAffected()
				if rowsAffected == 0 {
					http.Error(w, `{"error": "Feature tidak ditemukan"}`, http.StatusNotFound)
					return
				}
				clearTileCache(tableName)
				if oldGeom != "" && oldGeom != "null" {
					fID, _ := strconv.Atoi(featureID)
					db.Exec("INSERT INTO feature_history (table_name, feature_id, action, old_geom, old_properties, changed_by) VALUES ($1, $2, 'DELETE', $3, $4, $5)", tableName, fID, oldGeom, oldProps, token)
				}
				w.WriteHeader(http.StatusNoContent)
				return
			}

			if r.Method == "PUT" {
				w.Header().Set("Content-Type", "application/json")
				var body struct {
					Type       string                 `json:"type"`
					Geometry   interface{}            `json:"geometry"`
					Properties map[string]interface{} `json:"properties"`
				}
				if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
					http.Error(w, `{"error": "Format JSON tidak valid"}`, http.StatusBadRequest)
					return
				}

				geomBytes, err := json.Marshal(body.Geometry)
				if err != nil {
					http.Error(w, `{"error": "Format geometry salah"}`, http.StatusBadRequest)
					return
				}

				var exists bool
				err = db.QueryRow(fmt.Sprintf("SELECT EXISTS(SELECT 1 FROM %s WHERE id = $1)", tableName), featureID).Scan(&exists)
				if err != nil || !exists {
					http.Error(w, `{"error": "Feature tidak ditemukan"}`, http.StatusNotFound)
					return
				}

				var setClauses []string
				var vals []interface{}

				setClauses = append(setClauses, fmt.Sprintf("geom = ST_SetSRID(ST_GeomFromGeoJSON($1), %d)", srid))
				vals = append(vals, string(geomBytes))

				cleanProps := make(map[string]interface{})
				for k, v := range body.Properties {
					cleanProps[sanitizeIdentifier(k)] = v
				}
				body.Properties = cleanProps

				pCount := 1
				for _, col := range columns {
					if col == "id" {
						continue
					}
					if val, ok := body.Properties[col]; ok {
						pCount++
						setClauses = append(setClauses, fmt.Sprintf(`"%s" = $%d`, col, pCount))
						vals = append(vals, val)
					}
				}

				pCount++
				vals = append(vals, featureID)
				
				oldGeom, oldProps := getOldFeatureAsJSON(tableName, featureID)
				
				query := fmt.Sprintf("UPDATE %s SET %s WHERE id = $%d", tableName, strings.Join(setClauses, ", "), pCount)
				_, err = db.Exec(query, vals...)
				if err != nil {
					http.Error(w, fmt.Sprintf(`{"error": "Gagal update: %s"}`, err.Error()), http.StatusInternalServerError)
					return
				}
				clearTileCache(tableName)
				
				propsBytes, _ := json.Marshal(body.Properties)
				if oldGeom != "" && oldGeom != "null" {
					fID, _ := strconv.Atoi(featureID)
					db.Exec("INSERT INTO feature_history (table_name, feature_id, action, old_geom, new_geom, old_properties, new_properties, changed_by) VALUES ($1, $2, 'UPDATE', $3, $4, $5, $6, $7)", tableName, fID, oldGeom, string(geomBytes), oldProps, string(propsBytes), token)
				}

				w.WriteHeader(http.StatusNoContent)
				return
			}

			if r.Method == "PATCH" {
				w.Header().Set("Content-Type", "application/json")
				
				var patch struct {
					Geometry   *interface{}            `json:"geometry,omitempty"`
					Properties *map[string]interface{} `json:"properties,omitempty"`
				}
				if err := json.NewDecoder(r.Body).Decode(&patch); err != nil {
					http.Error(w, `{"error": "Format JSON patch tidak valid"}`, http.StatusBadRequest)
					return
				}

				var exists bool
				err = db.QueryRow(fmt.Sprintf("SELECT EXISTS(SELECT 1 FROM %s WHERE id = $1)", tableName), featureID).Scan(&exists)
				if err != nil || !exists {
					http.Error(w, `{"error": "Feature tidak ditemukan"}`, http.StatusNotFound)
					return
				}

				var setClauses []string
				var vals []interface{}
				pCount := 0

				if patch.Geometry != nil {
					geomBytes, err := json.Marshal(*patch.Geometry)
					if err != nil {
						http.Error(w, `{"error": "Format geometry salah"}`, http.StatusBadRequest)
						return
					}
					pCount++
					setClauses = append(setClauses, fmt.Sprintf("geom = ST_SetSRID(ST_GeomFromGeoJSON($%d), %d)", pCount, srid))
					vals = append(vals, string(geomBytes))
				}

				if patch.Properties != nil {
					cleanProps := make(map[string]interface{})
					for k, v := range *patch.Properties {
						cleanProps[sanitizeIdentifier(k)] = v
					}
					patch.Properties = &cleanProps

					for _, col := range columns {
						if col == "id" {
							continue
						}
						if val, ok := (*patch.Properties)[col]; ok {
							pCount++
							setClauses = append(setClauses, fmt.Sprintf(`"%s" = $%d`, col, pCount))
							vals = append(vals, val)
						}
					}
				}

				if pCount > 0 {
					pCount++
					vals = append(vals, featureID)
					
					oldGeom, oldProps := getOldFeatureAsJSON(tableName, featureID)
					
					query := fmt.Sprintf("UPDATE %s SET %s WHERE id = $%d", tableName, strings.Join(setClauses, ", "), pCount)
					_, err = db.Exec(query, vals...)
					if err != nil {
						http.Error(w, fmt.Sprintf(`{"error": "Gagal patch: %s"}`, err.Error()), http.StatusInternalServerError)
						return
					}
					clearTileCache(tableName)
					
					if oldGeom != "" && oldGeom != "null" {
						newGeom, newProps := getOldFeatureAsJSON(tableName, featureID)
						fID, _ := strconv.Atoi(featureID)
						db.Exec("INSERT INTO feature_history (table_name, feature_id, action, old_geom, new_geom, old_properties, new_properties, changed_by) VALUES ($1, $2, 'UPDATE', $3, $4, $5, $6, $7)", tableName, fID, oldGeom, newGeom, oldProps, newProps, token)
					}
				}

				w.WriteHeader(http.StatusNoContent)
				return
			}
		}
	}

	http.Error(w, "Endpoint tidak ditemukan", http.StatusNotFound)
}

// ================= CORS =================
func corsMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization, X-GISNAS-User, X-GISNAS-Role")
		if r.Method == "OPTIONS" {
			if strings.HasPrefix(r.URL.Path, "/api/ogc") || strings.HasPrefix(r.URL.Path, "/token/") {
				next.ServeHTTP(w, r)
				return
			}
			w.WriteHeader(http.StatusOK)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func main() {
	time.Sleep(2 * time.Second)
	initDB()

	mux := http.NewServeMux()
	
	// Auth
	mux.HandleFunc("/api/config", publicConfigHandler)
	mux.HandleFunc("/api/login", loginHandler)
	mux.HandleFunc("/api/register", registerHandler)

	// Workspaces
	mux.HandleFunc("/api/workspaces", func(w http.ResponseWriter, r *http.Request) {
		switch r.Method {
		case "GET":
			getWorkspacesHandler(w, r)
		case "POST":
			createWorkspaceHandler(w, r)
		case "DELETE":
			deleteWorkspaceHandler(w, r)
		default:
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		}
	})
	mux.HandleFunc("/api/workspaces/members", func(w http.ResponseWriter, r *http.Request) {
		switch r.Method {
		case "POST":
			addWorkspaceMemberHandler(w, r)
		case "DELETE":
			removeWorkspaceMemberHandler(w, r)
		case "PATCH":
			updateWorkspaceMemberPermissionsHandler(w, r)
		default:
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		}
	})
	mux.HandleFunc("/api/workspaces/invitations/respond", respondWorkspaceInvitationHandler)
	mux.HandleFunc("/api/users", listUsersHandler)

	// Admin User Management
	mux.HandleFunc("/api/admin/users", adminOnlyMiddleware(adminListUsersHandler))
	mux.HandleFunc("/api/admin/users/block", adminOnlyMiddleware(adminBlockUserHandler))
	mux.HandleFunc("/api/admin/users/unblock", adminOnlyMiddleware(adminUnblockUserHandler))
	mux.HandleFunc("/api/admin/users/create", adminOnlyMiddleware(adminCreateUserHandler))
	
	// SHP & Styling
	mux.HandleFunc("/api/upload", uploadSHPHandler)
	mux.HandleFunc("/api/datasets", getDatasetsHandler)
	mux.HandleFunc("/api/datasets/data", getDatasetDataHandler)
	mux.HandleFunc("/api/datasets/schema", getDatasetSchemaHandler)
	mux.HandleFunc("/api/datasets/insert", insertDatasetRowHandler)
	mux.HandleFunc("/api/datasets/create_blank", createBlankDatasetHandler)
	mux.HandleFunc("/api/datasets/delete_row", deleteDatasetRowHandler)
	mux.HandleFunc("/api/datasets/update_row", updateDatasetRowHandler)
	mux.HandleFunc("/api/datasets/add_column", addDatasetColumnHandler)
	mux.HandleFunc("/api/datasets/rename", renameDatasetHandler)
	mux.HandleFunc("/api/datasets/delete", deleteDatasetHandler)
	mux.HandleFunc("/api/styling", func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "GET" {
			getStylingHandler(w, r)
		} else if r.Method == "POST" {
			saveStylingHandler(w, r)
		} else {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		}
	})
	mux.HandleFunc("/api/tiles/", mvtTileHandler)

	// Tokens
	mux.HandleFunc("/api/tokens", listTokensHandler)
	mux.HandleFunc("/api/tokens/generate", generateTokenHandler)
	mux.HandleFunc("/api/tokens/toggle", toggleTokenHandler)
	mux.HandleFunc("/api/tokens/delete", deleteTokenHandler)

	// OGC API Protected Endpoints
	mux.HandleFunc("/api/ogc/features", ogcMiddleware(ogcFeaturesCRUDHandler))
	mux.HandleFunc("/api/ogc/features/", ogcMiddleware(ogcFeaturesCRUDHandler))
	mux.HandleFunc("/token/", ogcMiddleware(ogcFeaturesCRUDHandler))

	loggingMiddleware := func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			log.Printf("--> %s %s", r.Method, r.URL.String())
			next.ServeHTTP(w, r)
		})
	}

	fmt.Println("GISNAS Backend Production Server berjalan di port 8080...")
	log.Fatal(http.ListenAndServe(":8080", corsMiddleware(loggingMiddleware(mux))))
}
