import os
import struct

PAGE_SIZE = 128 
                
class Record:
    # (key: int, nombre: str[20], edad: int)
    FORMAT = "<i20si"
    SIZE = struct.calcsize(FORMAT)  # 28 bytes

    def __init__(self, key, nombre, edad):
        self.key = key
        self.nombre = nombre
        self.edad = edad

    def pack(self):
        return struct.pack(Record.FORMAT, self.key,
                           self.nombre.encode('utf-8')[:20].ljust(20, b' '),
                           self.edad)

    @staticmethod
    def unpack(data):
        key, nombre, edad = struct.unpack(Record.FORMAT, data)
        return Record(key, nombre.decode('utf-8', errors='ignore').rstrip(" \x00"), edad)

    def __repr__(self):
        return f"Record(key={self.key}, nombre={self.nombre}, edad={self.edad})"


class Page:
    # (num_records: int, next_page: int)
    # next_page: numero de la siguiente pagina de la cadena, o -1 si no hay
    HEADER_FORMAT = "<Ii"
    HEADER_SIZE = struct.calcsize(HEADER_FORMAT)  # 8 bytes
    CAPACIDAD = (PAGE_SIZE - HEADER_SIZE) // Record.SIZE  # factor de bloque

    def __init__(self, page_id, records=None, next_page=-1):
        self.page_id = page_id
        self.records = records if records is not None else []
        self.next_page = next_page

    def is_full(self):
        return len(self.records) >= Page.CAPACIDAD

    def is_empty(self):
        return len(self.records) == 0

    def find(self, key):
        # posicion del record dentro de la pagina, o -1
        for i, record in enumerate(self.records):
            if record.key == key:
                return i
        return -1

    def append(self, record):
        self.records.append(record)

    def remove_at(self, i):
        self.records[i] = self.records[-1]
        self.records.pop()

    def pack(self):
        data = struct.pack(Page.HEADER_FORMAT, len(self.records), self.next_page)
        for record in self.records:
            data += record.pack()
        return data + b'\x00' * (PAGE_SIZE - len(data))

    @staticmethod
    def unpack(page_id, data):
        num_records, next_page = struct.unpack_from(Page.HEADER_FORMAT, data, 0)
        records = []
        for i in range(num_records):
            inicio = Page.HEADER_SIZE + i * Record.SIZE
            records.append(Record.unpack(data[inicio: inicio + Record.SIZE]))
        return Page(page_id, records, next_page)

    def __repr__(self):
        return f"Page(id={self.page_id}, keys={[r.key for r in self.records]}, next={self.next_page})"


class HashFile:
    # (page_size: int, N: int, num_pages: int, free_page_head: int)
    FILE_HEADER_FORMAT = "<IIIi"
    FILE_HEADER_SIZE = struct.calcsize(FILE_HEADER_FORMAT)  # 16 bytes

    def __init__(self, filename, N=5):
        self.filename = filename
        if not os.path.exists(filename):
            self.create_file(N)
        self.N = self.read_file_header()[1]

    def create_file(self, N):
        with open(self.filename, "wb") as f:
            f.write(struct.pack(HashFile.FILE_HEADER_FORMAT, PAGE_SIZE, N, N, -1))
        for bucket in range(N):
            self.write_page(Page(bucket))  # N main buckets vacios

    def read_file_header(self):
        with open(self.filename, "rb") as f:
            data = f.read(HashFile.FILE_HEADER_SIZE)
            return struct.unpack(HashFile.FILE_HEADER_FORMAT, data)

    def write_file_header(self, page_size, N, num_pages, free_page_head):
        with open(self.filename, "r+b") as f:
            f.seek(0)
            f.write(struct.pack(HashFile.FILE_HEADER_FORMAT, page_size, N, num_pages, free_page_head))

    def page_offset(self, page_id):
        return HashFile.FILE_HEADER_SIZE + page_id * PAGE_SIZE

    def read_page(self, page_id):
        with open(self.filename, "rb") as f:
            f.seek(self.page_offset(page_id))
            return Page.unpack(page_id, f.read(PAGE_SIZE))

    def write_page(self, page):
        modo = "r+b" if os.path.exists(self.filename) else "wb"
        with open(self.filename, modo) as f:
            f.seek(self.page_offset(page.page_id))
            f.write(page.pack())

    def new_page(self):
        # reusa una pagina de la free list antes de hacer crecer el archivo
        page_size, N, num_pages, free_page_head = self.read_file_header()
        if free_page_head != -1:
            page_id = free_page_head
            siguiente_libre = self.read_page(page_id).next_page
            self.write_file_header(page_size, N, num_pages, siguiente_libre)
        else:
            page_id = num_pages
            self.write_file_header(page_size, N, num_pages + 1, free_page_head)
        page = Page(page_id)
        self.write_page(page)
        return page

    def free_page(self, page):
        # encadena la pagina al frente de la free list
        page_size, N, num_pages, free_page_head = self.read_file_header()
        self.write_page(Page(page.page_id, [], free_page_head))
        self.write_file_header(page_size, N, num_pages, page.page_id)

    # funcion hash
    def hash_key(self, key):
        return hash(key) % self.N


    # helper para los tests
    def chain(self, bucket):
        # paginas de la cadena del bucket: main + overflow
        pages = []
        page_id = bucket
        while page_id != -1:
            page = self.read_page(page_id)
            pages.append(page)
            page_id = page.next_page
        return pages

    


    def search(self, key):
        page_id = self.hash_key(key)
        while page_id != -1:
            page = self.read_page(page_id)
            i = page.find(key)
            if i != -1:
                return page.records[i]
            page_id = page.next_page
        return None

    def insert(self, record):
        bucket = self.hash_key(record.key)

        # recorre toda la cadena de buckets verificando que la key no exista
        page_con_espacio = None
        ultima = None
        page_id = bucket
        while page_id != -1:
            page = self.read_page(page_id)
            if page.find(record.key) != -1:
                return False  # duplicado
            if page_con_espacio is None and not page.is_full():
                page_con_espacio = page
            ultima = page
            page_id = page.next_page

        if page_con_espacio is None:
            page_con_espacio = self.new_page()
            ultima.next_page = page_con_espacio.page_id
            self.write_page(ultima)

        page_con_espacio.append(record)
        self.write_page(page_con_espacio)
        return True

    def remove(self, key):
        bucket = self.hash_key(key)

        # localiza el record guardando la pagina anterior de la cadena
        anterior = None
        page = self.read_page(bucket)
        while True:
            i = page.find(key)
            if i != -1:
                break
            if page.next_page == -1:
                return False
            anterior = page
            page = self.read_page(page.next_page)

        page.remove_at(i)  # eliminacion fisica
        self.write_page(page)

        # si la pagina de overflow quedo vacia se desenlaza y va a la free list
        if page.page_id != bucket and page.is_empty():
            anterior.next_page = page.next_page
            self.write_page(anterior)
            self.free_page(page)

        return True

    # TEST
    # TEST
    # TEST
    # TEST

    def load(self):
        records = []
        for bucket in range(self.N):
            for page in self.chain(bucket):
                records.extend(page.records)
        return records

    def free_list(self):
        # page_ids de las paginas liberadas, siguiendo la lista
        pages = []
        page_id = self.read_file_header()[3]
        while page_id != -1:
            pages.append(page_id)
            page_id = self.read_page(page_id).next_page
        return pages

    def print_estado(self):
        page_size, N, num_pages, free_page_head = self.read_file_header()
        libres = self.free_list()
        print(f"  archivo: {os.path.getsize(self.filename)} bytes | {num_pages} paginas "
              f"({N} main + {num_pages - N} overflow) | free list: {libres or 'vacia'}")
        for bucket in range(N):
            partes = []
            for page in self.chain(bucket):
                etiqueta = "main" if page.page_id == bucket else " ovf"
                keys = " ".join(f"{r.key:>4}" for r in page.records)
                partes.append(f"{etiqueta}[{page.page_id}] {keys:<19}")
            print((f"  bucket {bucket}:  " + " -> ".join(partes)).rstrip())

def ubicar(hf, key):
    # en que pagina de la cadena esta la key (solo para el output del test)
    bucket = hf.hash_key(key)
    for page in hf.chain(bucket):
        if page.find(key) != -1:
            tipo = "main" if page.page_id == bucket else "ovf"
            return f"en bucket {bucket}, {tipo}[{page.page_id}]"
    return f"no esta en el bucket {bucket}"


if __name__ == "__main__":
    filename = "static_hash.dat"
    if os.path.exists(filename):
        os.remove(filename)

    hf = HashFile(filename, N=3)
    keys = list(range(10, 190, 10))  # 18 keys: 6 por bucket -> fuerzan overflow

    print(f"Record.SIZE = {Record.SIZE} bytes | PAGE_SIZE = {PAGE_SIZE} bytes | "
          f"capacidad = {Page.CAPACIDAD} records por pagina | N = {hf.N} buckets")
    print(f"bucket = hash(key) % {hf.N}")

    print("\n=== 1. INSERCION de 18 keys: 10, 20, 30, ... 180 ===")
    for key in keys:
        assert hf.insert(Record(key, f"nombre{key}", 20 + key % 40))
    print("  cada bucket recibe 6 keys: llena su main (4) y encadena una pagina de overflow")
    assert hf.read_file_header()[2] == 6
    print("  insert(10) de nuevo ->", hf.insert(Record(10, "duplicado", 99)), "(duplicado)")
    hf.print_estado()

    print("\n=== 2. BUSQUEDA ===")
    for key in keys:
        encontrado = hf.search(key)
        assert encontrado is not None and encontrado.key == key
    print(f"  las {len(keys)} keys insertadas se encuentran")
    print(f"  search(70)  -> {hf.search(70)}  {ubicar(hf, 70)}")
    print(f"  search(180) -> {hf.search(180)}  {ubicar(hf, 180)}")
    assert hf.search(999) is None
    print(f"  search(999) -> {hf.search(999)}  (key inexistente)")

    print("\n=== 3. ELIMINACION de 150, 180, 10, 40, 80 ===")
    for key in [150, 180, 10, 40, 80]:
        assert hf.remove(key)
    print("  150 y 180 eran los unicos del overflow del bucket 0: esa pagina quedo")
    print("  vacia, se desenlazo y paso a la free list (la cadena bajo de 2 a 1 pagina)")
    print("  10, 40 y 80 dejan espacio libre en sus main buckets, sin promocion:")
    print("  nadie sube desde el overflow a rellenarlos")
    print("  remove(10) otra vez ->", hf.remove(10), "| remove(999) ->", hf.remove(999))
    assert len(hf.chain(0)) == 1 and hf.free_list() == [5]
    hf.print_estado()

    vivos = sorted(r.key for r in hf.load())
    assert vivos == sorted(set(keys) - {150, 180, 10, 40, 80})
    assert all(hf.search(key) is None for key in [150, 180, 10, 40, 80])
    assert all(hf.search(key) is not None for key in vivos)
    print(f"  quedan {len(vivos)} vivas:", " ".join(str(k) for k in vivos))

    print("\n=== 4. REUTILIZACION de la pagina liberada ===")
    num_pages_antes = hf.read_file_header()[2]
    for key in [210, 240]:  # ambas al bucket 0, que tiene el main lleno
        assert hf.insert(Record(key, f"nombre{key}", 25))
    print("  210 y 240 caen en el bucket 0, cuyo main sigue lleno -> necesita overflow")
    print("  new_page saca la pagina 5 de la free list en vez de crecer el archivo:")
    print(f"  el archivo sigue en {num_pages_antes} paginas")
    assert len(hf.chain(0)) == 2 and hf.read_file_header()[2] == num_pages_antes
    assert hf.free_list() == []
    hf.print_estado()

    print("\nok: todos los asserts pasaron")
