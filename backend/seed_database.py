from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from werkzeug.security import generate_password_hash

from config import Config
from database import (
    get_cinemas_collection,
    get_coupons_collection,
    get_movies_collection,
    get_screens_collection,
    get_shows_collection,
    get_snacks_collection,
    get_users_collection,
    initialize_database,
)
from utils.validators import normalize_movie_title


def now():
    return datetime.now(timezone.utc)


MOVIES_DATA = [
    {
        "title": "Interstellar",
        "year": "2014",
        "genres": ["Science Fiction", "Drama", "Adventure"],
        "language": "English",
        "duration": "169 minutes",
        "director": "Christopher Nolan",
        "cast": ["Matthew McConaughey", "Anne Hathaway", "Jessica Chastain", "Michael Caine"],
        "description": "When Earth becomes uninhabitable in the future, a farmer and ex-NASA pilot, Joseph Cooper, is tasked to pilot a spacecraft, along with a team of researchers, to find a new planet for humans.",
        "rating": 8.7,
        "age_rating": "UA",
        "poster_url": "https://images.unsplash.com/photo-1534447677768-be436bb09401?auto=format&fit=crop&w=600&q=80",
        "backdrop_url": "https://images.unsplash.com/photo-1506703719100-a0f3a48c0f86?auto=format&fit=crop&w=1200&q=80",
        "trailer_url": "https://www.youtube.com/watch?v=zSWdZVtXT7E",
        "is_now_showing": True,
        "is_trending": True,
        "is_popular": True,
        "is_coming_soon": False,
    },
    {
        "title": "The Dark Knight",
        "year": "2008",
        "genres": ["Action", "Crime", "Drama"],
        "language": "English",
        "duration": "152 minutes",
        "director": "Christopher Nolan",
        "cast": ["Christian Bale", "Heath Ledger", "Aaron Eckhart", "Gary Oldman", "Michael Caine"],
        "description": "When the menace known as the Joker wreaks havoc and chaos on the people of Gotham, Batman must accept one of the greatest psychological and physical tests of his ability to fight injustice.",
        "rating": 9.0,
        "age_rating": "UA",
        "poster_url": "https://images.unsplash.com/photo-1509198397868-475647b2a1e5?auto=format&fit=crop&w=600&q=80",
        "backdrop_url": "https://images.unsplash.com/photo-1518709268805-4e9042af9f23?auto=format&fit=crop&w=1200&q=80",
        "trailer_url": "https://www.youtube.com/watch?v=EXeTwQWrcwY",
        "is_now_showing": True,
        "is_trending": True,
        "is_popular": True,
        "is_coming_soon": False,
    },
    {
        "title": "Inception",
        "year": "2010",
        "genres": ["Action", "Science Fiction", "Thriller"],
        "language": "English",
        "duration": "148 minutes",
        "director": "Christopher Nolan",
        "cast": ["Leonardo DiCaprio", "Joseph Gordon-Levitt", "Elliot Page", "Tom Hardy", "Ken Watanabe"],
        "description": "A thief who steals corporate secrets through the use of dream-sharing technology is given the inverse task of planting an idea into the mind of a C.E.O.",
        "rating": 8.8,
        "age_rating": "UA",
        "poster_url": "https://images.unsplash.com/photo-1478760329108-5c3ed9d495a0?auto=format&fit=crop&w=600&q=80",
        "backdrop_url": "https://images.unsplash.com/photo-1451187580459-43490279c0fa?auto=format&fit=crop&w=1200&q=80",
        "trailer_url": "https://www.youtube.com/watch?v=YoHD9XEInc0",
        "is_now_showing": True,
        "is_trending": True,
        "is_popular": True,
        "is_coming_soon": False,
    },
    {
        "title": "Avengers: Endgame",
        "year": "2019",
        "genres": ["Action", "Science Fiction", "Adventure"],
        "language": "English",
        "duration": "181 minutes",
        "director": "Anthony Russo, Joe Russo",
        "cast": ["Robert Downey Jr.", "Chris Evans", "Mark Ruffalo", "Chris Hemsworth", "Scarlett Johansson"],
        "description": "After the devastating events of Infinity War, the universe is in ruins. With the help of remaining allies, the Avengers assemble once more in order to reverse Thanos' actions.",
        "rating": 8.4,
        "age_rating": "UA",
        "poster_url": "https://images.unsplash.com/photo-1635805737707-575885ab0820?auto=format&fit=crop&w=600&q=80",
        "backdrop_url": "https://images.unsplash.com/photo-1607604276583-eef5d076aa5f?auto=format&fit=crop&w=1200&q=80",
        "trailer_url": "https://www.youtube.com/watch?v=TcMBFSGVi1c",
        "is_now_showing": True,
        "is_trending": True,
        "is_popular": True,
        "is_coming_soon": False,
    },
    {
        "title": "3 Idiots",
        "year": "2009",
        "genres": ["Comedy", "Drama"],
        "language": "Hindi",
        "duration": "170 minutes",
        "director": "Rajkumar Hirani",
        "cast": ["Aamir Khan", "R. Madhavan", "Sharman Joshi", "Kareena Kapoor", "Boman Irani"],
        "description": "Two friends are searching for their long lost companion. They revisit their college days and recall the memories of their friend who inspired them to think differently.",
        "rating": 8.4,
        "age_rating": "U",
        "poster_url": "https://images.unsplash.com/photo-1517604931442-7e0c8ed2963c?auto=format&fit=crop&w=600&q=80",
        "backdrop_url": "https://images.unsplash.com/photo-1524995997946-a1c2e315a42f?auto=format&fit=crop&w=1200&q=80",
        "trailer_url": "https://www.youtube.com/watch?v=K0eDlFX9GMc",
        "is_now_showing": True,
        "is_trending": True,
        "is_popular": True,
        "is_coming_soon": False,
    },
    {
        "title": "Dangal",
        "year": "2016",
        "genres": ["Biography", "Drama", "Sport"],
        "language": "Hindi",
        "duration": "161 minutes",
        "director": "Nitesh Tiwari",
        "cast": ["Aamir Khan", "Fatima Sana Shaikh", "Sanya Malhotra", "Sakshi Tanwar"],
        "description": "Former wrestler Mahavir Singh Phogat and his two wrestler daughters struggle towards glory at the Commonwealth Games in the face of societal oppression.",
        "rating": 8.3,
        "age_rating": "U",
        "poster_url": "https://images.unsplash.com/photo-1517838277536-f5f99be501cd?auto=format&fit=crop&w=600&q=80",
        "backdrop_url": "https://images.unsplash.com/photo-1461896836934-ffe607ba8211?auto=format&fit=crop&w=1200&q=80",
        "trailer_url": "https://www.youtube.com/watch?v=x_7YlGv9u1g",
        "is_now_showing": True,
        "is_trending": True,
        "is_popular": True,
        "is_coming_soon": False,
    },
    {
        "title": "Zindagi Na Milegi Dobara",
        "year": "2011",
        "genres": ["Comedy", "Drama", "Romance"],
        "language": "Hindi",
        "duration": "155 minutes",
        "director": "Zoya Akhtar",
        "cast": ["Hrithik Roshan", "Farhan Akhtar", "Abhay Deol", "Katrina Kaif", "Kalki Koechlin"],
        "description": "Three friends decide to turn their fantasy vacation into reality after one of their friends gets engaged. A journey of self-discovery, thrill, and enduring friendship across Spain.",
        "rating": 8.2,
        "age_rating": "UA",
        "poster_url": "https://images.unsplash.com/photo-1469854523086-cc02fe5d8800?auto=format&fit=crop&w=600&q=80",
        "backdrop_url": "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=1200&q=80",
        "trailer_url": "https://www.youtube.com/watch?v=FJrpcDgC3zU",
        "is_now_showing": True,
        "is_trending": True,
        "is_popular": True,
        "is_coming_soon": False,
    },
    {
        "title": "Andhadhun",
        "year": "2018",
        "genres": ["Crime", "Comedy", "Thriller"],
        "language": "Hindi",
        "duration": "139 minutes",
        "director": "Sriram Raghavan",
        "cast": ["Ayushmann Khurrana", "Tabu", "Radhika Apte", "Anil Dhawan"],
        "description": "A series of mysterious events changes the life of a blind pianist, who now must report a crime that he should technically not know about.",
        "rating": 8.2,
        "age_rating": "UA",
        "poster_url": "https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?auto=format&fit=crop&w=600&q=80",
        "backdrop_url": "https://images.unsplash.com/photo-1514525253161-7a46d19cd819?auto=format&fit=crop&w=1200&q=80",
        "trailer_url": "https://www.youtube.com/watch?v=2iVYI99VGaw",
        "is_now_showing": True,
        "is_trending": True,
        "is_popular": True,
        "is_coming_soon": False,
    },
    {
        "title": "Parasite",
        "year": "2019",
        "genres": ["Drama", "Thriller", "Comedy"],
        "language": "Korean",
        "duration": "132 minutes",
        "director": "Bong Joon Ho",
        "cast": ["Song Kang-ho", "Lee Sun-kyun", "Cho Yeo-jeong", "Choi Woo-shik"],
        "description": "Greed and class discrimination threaten the newly formed symbiotic relationship between the wealthy Park family and the destitute Kim clan.",
        "rating": 8.5,
        "age_rating": "A",
        "poster_url": "https://images.unsplash.com/photo-1518709268805-4e9042af9f23?auto=format&fit=crop&w=600&q=80",
        "backdrop_url": "https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?auto=format&fit=crop&w=1200&q=80",
        "trailer_url": "https://www.youtube.com/watch?v=5xH0RzeSojI",
        "is_now_showing": True,
        "is_trending": True,
        "is_popular": True,
        "is_coming_soon": False,
    },
    {
        "title": "Dune: Part Two",
        "year": "2024",
        "genres": ["Science Fiction", "Action", "Adventure"],
        "language": "English",
        "duration": "166 minutes",
        "director": "Denis Villeneuve",
        "cast": ["Timothée Chalamet", "Zendaya", "Rebecca Ferguson", "Javier Bardem", "Austin Butler"],
        "description": "Paul Atreides unites with Chani and the Fremen while seeking revenge against the conspirators who destroyed his family, facing a choice between love and the fate of the universe.",
        "rating": 8.6,
        "age_rating": "UA",
        "poster_url": "https://images.unsplash.com/photo-1509316975850-ff9c5deb0cd9?auto=format&fit=crop&w=600&q=80",
        "backdrop_url": "https://images.unsplash.com/photo-1518709268805-4e9042af9f23?auto=format&fit=crop&w=1200&q=80",
        "trailer_url": "https://www.youtube.com/watch?v=Way9Dexny3w",
        "is_now_showing": True,
        "is_trending": True,
        "is_popular": True,
        "is_coming_soon": False,
    },
    {
        "title": "Oppenheimer",
        "year": "2023",
        "genres": ["Biography", "Drama", "History"],
        "language": "English",
        "duration": "180 minutes",
        "director": "Christopher Nolan",
        "cast": ["Cillian Murphy", "Emily Blunt", "Matt Damon", "Robert Downey Jr.", "Florence Pugh"],
        "description": "The story of American scientist J. Robert Oppenheimer and his role in the development of the atomic bomb during World War II.",
        "rating": 8.9,
        "age_rating": "UA",
        "poster_url": "https://images.unsplash.com/photo-1440404653325-ab127d49abc1?auto=format&fit=crop&w=600&q=80",
        "backdrop_url": "https://images.unsplash.com/photo-1451187580459-43490279c0fa?auto=format&fit=crop&w=1200&q=80",
        "trailer_url": "https://www.youtube.com/watch?v=uYPbbksJxIg",
        "is_now_showing": True,
        "is_trending": True,
        "is_popular": True,
        "is_coming_soon": False,
    },
    {
        "title": "Avatar: Fire and Ash",
        "year": "2025",
        "genres": ["Action", "Adventure", "Fantasy", "Science Fiction"],
        "language": "English",
        "duration": "190 minutes",
        "director": "James Cameron",
        "cast": ["Sam Worthington", "Zoe Saldana", "Sigourney Weaver", "Stephen Lang"],
        "description": "The saga of Jake Sully and Neytiri continues as they encounter a volatile new clan of Na'vi known as the Ash People on the breathtaking moon of Pandora.",
        "rating": 8.8,
        "age_rating": "UA",
        "poster_url": "https://images.unsplash.com/photo-1518709268805-4e9042af9f23?auto=format&fit=crop&w=600&q=80",
        "backdrop_url": "https://images.unsplash.com/photo-1506703719100-a0f3a48c0f86?auto=format&fit=crop&w=1200&q=80",
        "trailer_url": "https://www.youtube.com/watch?v=d9MyW72ELq0",
        "is_now_showing": False,
        "is_trending": False,
        "is_popular": True,
        "is_coming_soon": True,
    },
    {
        "title": "Kalki 2898 AD",
        "year": "2024",
        "genres": ["Action", "Science Fiction", "Drama"],
        "language": "Telugu, Hindi, Tamil",
        "duration": "181 minutes",
        "director": "Nag Ashwin",
        "cast": ["Prabhas", "Amitabh Bachchan", "Kamal Haasan", "Deepika Padukone"],
        "description": "A modern avatar of Vishnu descends to Earth to protect the world from evil forces in a post-apocalyptic future set in the sacred city of Kasi.",
        "rating": 7.7,
        "age_rating": "UA",
        "poster_url": "https://images.unsplash.com/photo-1579783900882-c0d3dad7b119?auto=format&fit=crop&w=600&q=80",
        "backdrop_url": "https://images.unsplash.com/photo-1518709268805-4e9042af9f23?auto=format&fit=crop&w=1200&q=80",
        "trailer_url": "https://www.youtube.com/watch?v=kQDd1AhGIHk",
        "is_now_showing": True,
        "is_trending": True,
        "is_popular": True,
        "is_coming_soon": False,
    },
    {
        "title": "Spirited Away",
        "year": "2001",
        "genres": ["Animation", "Adventure", "Fantasy"],
        "language": "Japanese",
        "duration": "125 minutes",
        "director": "Hayao Miyazaki",
        "cast": ["Rumi Hiiragi", "Miyu Irino", "Mari Natsuki"],
        "description": "During her family's move to the suburbs, a sullen 10-year-old girl wanders into a world ruled by gods, witches, and spirits, and where humans are changed into beasts.",
        "rating": 8.6,
        "age_rating": "U",
        "poster_url": "https://images.unsplash.com/photo-1534447677768-be436bb09401?auto=format&fit=crop&w=600&q=80",
        "backdrop_url": "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=1200&q=80",
        "trailer_url": "https://www.youtube.com/watch?v=ByXuk9QqQkk",
        "is_now_showing": True,
        "is_trending": False,
        "is_popular": True,
        "is_coming_soon": False,
    },
    {
        "title": "The Shawshank Redemption",
        "year": "1994",
        "genres": ["Drama"],
        "language": "English",
        "duration": "142 minutes",
        "director": "Frank Darabont",
        "cast": ["Tim Robbins", "Morgan Freeman", "Bob Gunton", "William Sadler"],
        "description": "Over the course of several years, two convicts form a friendship, seeking solace and eventual redemption through basic compassion.",
        "rating": 9.3,
        "age_rating": "A",
        "poster_url": "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?auto=format&fit=crop&w=600&q=80",
        "backdrop_url": "https://images.unsplash.com/photo-1478760329108-5c3ed9d495a0?auto=format&fit=crop&w=1200&q=80",
        "trailer_url": "https://www.youtube.com/watch?v=6hB3S9bIaco",
        "is_now_showing": True,
        "is_trending": False,
        "is_popular": True,
        "is_coming_soon": False,
    },
    {
        "title": "Everything Everywhere All at Once",
        "year": "2022",
        "genres": ["Action", "Comedy", "Science Fiction"],
        "language": "English",
        "duration": "139 minutes",
        "director": "Daniel Kwan, Daniel Scheinert",
        "cast": ["Michelle Yeoh", "Ke Huy Quan", "Stephanie Hsu", "Jamie Lee Curtis"],
        "description": "A middle-aged Chinese immigrant is swept up into an insane adventure in which she alone can save existence by exploring other universes and connecting with the lives she could have led.",
        "rating": 7.8,
        "age_rating": "A",
        "poster_url": "https://images.unsplash.com/photo-1518709268805-4e9042af9f23?auto=format&fit=crop&w=600&q=80",
        "backdrop_url": "https://images.unsplash.com/photo-1451187580459-43490279c0fa?auto=format&fit=crop&w=1200&q=80",
        "trailer_url": "https://www.youtube.com/watch?v=wxN1T1uxQ2g",
        "is_now_showing": True,
        "is_trending": False,
        "is_popular": True,
        "is_coming_soon": False,
    },
]


CINEMAS_DATA = [
    # Mumbai
    {
        "name": "PVR ICON: Phoenix Palladium",
        "city": "Mumbai",
        "location": "Lower Parel",
        "address": "462, Senapati Bapat Marg, Lower Parel, Mumbai, Maharashtra 400013",
        "amenities": ["IMAX Laser", "Dolby Atmos", "Recliner Seats", "Gourmet Food", "Valet Parking"],
        "screens_count": 5,
        "contact_phone": "+91 22 4333 9999",
        "rating": 4.8,
        "image_url": "https://images.unsplash.com/photo-1517604931442-7e0c8ed2963c?auto=format&fit=crop&w=600&q=80",
    },
    {
        "name": "INOX Megaplex: Inorbit Mall",
        "city": "Mumbai",
        "location": "Malad West",
        "address": "Inorbit Mall, Link Road, Malad West, Mumbai, Maharashtra 400064",
        "amenities": ["IMAX", "MX4D", "ScreenX", "Dolby Atmos", "Kiddles Play Area"],
        "screens_count": 11,
        "contact_phone": "+91 22 6677 8899",
        "rating": 4.7,
        "image_url": "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?auto=format&fit=crop&w=600&q=80",
    },
    {
        "name": "Maison PVR: Jio World Drive",
        "city": "Mumbai",
        "location": "BKC",
        "address": "Jio World Drive, Bandra Kurla Complex, Bandra East, Mumbai, Maharashtra 400051",
        "amenities": ["Director's Cut", "Dolby Atmos", "Luxury Lounges", "Butler on Call"],
        "screens_count": 6,
        "contact_phone": "+91 22 3500 1200",
        "rating": 4.9,
        "image_url": "https://images.unsplash.com/photo-1578849278619-e73505e9610f?auto=format&fit=crop&w=600&q=80",
    },
    # Delhi-NCR
    {
        "name": "PVR Director's Cut: Ambience Mall",
        "city": "Delhi-NCR",
        "location": "Vasant Kunj",
        "address": "Ambience Mall, Nelson Mandela Marg, Vasant Kunj, New Delhi 110070",
        "amenities": ["Ultra Luxury Recliners", "Personal Concierge", "Chef Crafted Menu", "Dolby Atmos"],
        "screens_count": 4,
        "contact_phone": "+91 11 4087 0000",
        "rating": 4.9,
        "image_url": "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?auto=format&fit=crop&w=600&q=80",
    },
    {
        "name": "Cinepolis: DLF Avenue",
        "city": "Delhi-NCR",
        "location": "Saket",
        "address": "DLF Avenue Mall, A4, Press Enclave Marg, Saket District Centre, New Delhi 110017",
        "amenities": ["IMAX", "4DX", "Dolby Atmos", "VIP Lounge", "Recliners"],
        "screens_count": 6,
        "contact_phone": "+91 11 4108 5522",
        "rating": 4.7,
        "image_url": "https://images.unsplash.com/photo-1517604931442-7e0c8ed2963c?auto=format&fit=crop&w=600&q=80",
    },
    # Bengaluru
    {
        "name": "PVR IMAX: Forum Mall",
        "city": "Bengaluru",
        "location": "Koramangala",
        "address": "The Forum Mall, 21, Hosur Road, Koramangala, Bengaluru, Karnataka 560095",
        "amenities": ["IMAX with Laser", "Dolby Atmos", "Recliner Seats", "Food Court"],
        "screens_count": 8,
        "contact_phone": "+91 80 2206 7878",
        "rating": 4.8,
        "image_url": "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?auto=format&fit=crop&w=600&q=80",
    },
    {
        "name": "INOX: Nexus Mall",
        "city": "Bengaluru",
        "location": "Whitefield",
        "address": "Nexus Whitefield Mall, ITPL Main Road, Whitefield, Bengaluru, Karnataka 560066",
        "amenities": ["Insignia Lounge", "Laser Projection", "Dolby Atmos", "Recliners"],
        "screens_count": 6,
        "contact_phone": "+91 80 6726 6666",
        "rating": 4.6,
        "image_url": "https://images.unsplash.com/photo-1517604931442-7e0c8ed2963c?auto=format&fit=crop&w=600&q=80",
    },
    # Hyderabad
    {
        "name": "Prasads Multiplex: Large Screen",
        "city": "Hyderabad",
        "location": "Necklace Road",
        "address": "Prasads IMAX, NTR Marg, Central Secretariat, Khairatabad, Hyderabad 500004",
        "amenities": ["Giant Screen", "Dual 4K Laser", "Dolby Atmos", "Gaming Zone", "Food Court"],
        "screens_count": 7,
        "contact_phone": "+91 40 2344 8888",
        "rating": 4.9,
        "image_url": "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?auto=format&fit=crop&w=600&q=80",
    },
    # Chennai
    {
        "name": "SPI Cinemas (Sathyam)",
        "city": "Chennai",
        "location": "Royapettah",
        "address": "8, Thiru Vi Ka Road, Royapettah, Chennai, Tamil Nadu 600014",
        "amenities": ["Dolby Atmos", "Famous Popcorn Bar", "Laser Projection", "Reserved Parking"],
        "screens_count": 6,
        "contact_phone": "+91 44 4224 4224",
        "rating": 4.9,
        "image_url": "https://images.unsplash.com/photo-1517604931442-7e0c8ed2963c?auto=format&fit=crop&w=600&q=80",
    },
    # Pune
    {
        "name": "Cinepolis: Seasons Mall",
        "city": "Pune",
        "location": "Magarpatta",
        "address": "Seasons Mall, Magarpatta City, Hadapsar, Pune, Maharashtra 411028",
        "amenities": ["VIP Club", "Dolby 7.1", "RealD 3D", "Recliner Seats"],
        "screens_count": 15,
        "contact_phone": "+91 20 6723 3333",
        "rating": 4.7,
        "image_url": "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?auto=format&fit=crop&w=600&q=80",
    },
]


COUPONS_DATA = [
    {"code": "CINEPASS20", "discount_type": "percentage", "discount_value": 20.0, "min_amount": 300.0, "max_discount": 150.0, "active": True},
    {"code": "WELCOME50", "discount_type": "fixed", "discount_value": 50.0, "min_amount": 250.0, "max_discount": 50.0, "active": True},
    {"code": "FLAT100", "discount_type": "fixed", "discount_value": 100.0, "min_amount": 600.0, "max_discount": 100.0, "active": True},
    {"code": "BLOCKBUSTER", "discount_type": "percentage", "discount_value": 25.0, "min_amount": 500.0, "max_discount": 200.0, "active": True},
    {"code": "WEEKENDVIBES", "discount_type": "percentage", "discount_value": 15.0, "min_amount": 400.0, "max_discount": 120.0, "active": True},
]


SNACKS_DATA = [
    {"id": "snk-1", "name": "Large Butter Popcorn", "category": "popcorn", "price": 280.0, "description": "Crispy golden popcorn tossed in creamy melted butter.", "image_url": "https://images.unsplash.com/photo-1578849278619-e73505e9610f?auto=format&fit=crop&w=400&q=80", "is_available": True},
    {"id": "snk-2", "name": "Caramel Gourmet Popcorn", "category": "popcorn", "price": 320.0, "description": "Sweet crunchy kettle corn coated with rich golden caramel.", "image_url": "https://images.unsplash.com/photo-1512149177596-f817c7ef5d4c?auto=format&fit=crop&w=400&q=80", "is_available": True},
    {"id": "snk-3", "name": "Classic Movie Nachos & Salsa", "category": "snacks", "price": 240.0, "description": "Crispy tortilla chips served with zesty salsa and warm cheese dip.", "image_url": "https://images.unsplash.com/photo-1513456852971-30c0b8199d4d?auto=format&fit=crop&w=400&q=80", "is_available": True},
    {"id": "snk-4", "name": "Cold Coca-Cola (Large)", "category": "beverages", "price": 180.0, "description": "Refreshing ice-cold fountain beverage (650ml).", "image_url": "https://images.unsplash.com/photo-1622483767028-3f66f32aef97?auto=format&fit=crop&w=400&q=80", "is_available": True},
    {"id": "snk-5", "name": "Fresh Lemon Iced Tea", "category": "beverages", "price": 190.0, "description": "Chilled black tea brewed with organic lemons and mint leaves.", "image_url": "https://images.unsplash.com/photo-1556679343-c7306c1976bc?auto=format&fit=crop&w=400&q=80", "is_available": True},
    {"id": "snk-6", "name": "Blockbuster Couple Combo", "category": "combos", "price": 540.0, "description": "1 Large Tub Popcorn + 2 Large Fountain Drinks + 1 Nachos.", "image_url": "https://images.unsplash.com/photo-1585647347384-2593bc35786b?auto=format&fit=crop&w=400&q=80", "is_available": True},
]


def seed_all():
    print("Starting Cinepass database seeding...")
    class AppConfig(dict):
        def __getitem__(self, key):
            return getattr(Config, key)
    class DummyApp:
        config = AppConfig()

    initialize_database(DummyApp())

    # 1. Seed Movies
    movies_coll = get_movies_collection()
    movie_id_map = {}
    for m in MOVIES_DATA:
        norm = normalize_movie_title(m["title"])
        doc = dict(m)
        doc["normalized_title"] = norm
        doc["created_at"] = now()
        doc["updated_at"] = now()

        existing = movies_coll.find_one({"normalized_title": norm})
        if existing:
            movies_coll.update_one({"normalized_title": norm}, {"$set": doc})
            movie_id_map[m["title"]] = str(existing["_id"])
        else:
            res = movies_coll.insert_one(doc)
            movie_id_map[m["title"]] = str(res.inserted_id)

    print(f"Seeded {len(MOVIES_DATA)} movies successfully.")

    # 2. Seed Cinemas and Screens
    cinemas_coll = get_cinemas_collection()
    screens_coll = get_screens_collection()
    cinema_id_map = {}

    for c in CINEMAS_DATA:
        existing_c = cinemas_coll.find_one({"name": c["name"], "city": c["city"]})
        c_doc = dict(c)
        c_doc["created_at"] = now()
        c_doc["updated_at"] = now()
        if existing_c:
            c_id = str(existing_c["_id"])
            cinemas_coll.update_one({"_id": existing_c["_id"]}, {"$set": c_doc})
        else:
            res = cinemas_coll.insert_one(c_doc)
            c_id = str(res.inserted_id)
        cinema_id_map[c["name"]] = c_id

        # Seed Screens for this cinema
        screen_types = [("Screen 1", "IMAX Laser"), ("Screen 2", "Dolby Atmos"), ("Screen 3", "Director's Cut"), ("Screen 4", "Standard")]
        for s_idx, (s_name, s_type) in enumerate(screen_types[:c.get("screens_count", 4)], start=1):
            existing_s = screens_coll.find_one({"cinema_id": c_id, "screen_name": s_name})
            s_doc = {
                "cinema_id": c_id,
                "screen_name": s_name,
                "screen_type": s_type,
                "total_seats": 160,
                "created_at": now(),
            }
            if not existing_s:
                screens_coll.insert_one(s_doc)

    print(f"Seeded {len(CINEMAS_DATA)} premier cinemas with multi-tier screens.")

    # 3. Seed Shows for Today and Next 7 Days
    shows_coll = get_shows_collection()
    standard_timings = ["10:30 AM", "01:45 PM", "05:00 PM", "08:15 PM", "11:00 PM"]
    today = datetime.now()

    shows_count = 0
    all_cinemas = list(cinemas_coll.find())
    all_movies = list(movies_coll.find({"is_now_showing": True}))

    # Schedule shows for the next 7 days
    for day_offset in range(7):
        target_date = (today + timedelta(days=day_offset)).strftime("%Y-%m-%d")
        for cinema in all_cinemas:
            c_id = str(cinema["_id"])
            screens = list(screens_coll.find({"cinema_id": c_id}))
            if not screens:
                continue

            for s_idx, screen in enumerate(screens):
                # Pick a movie for this screen
                movie = all_movies[(day_offset + s_idx) % len(all_movies)]
                m_id = str(movie["_id"])

                # Add 2-3 showtimes per screen per day
                for t_idx in range(len(standard_timings[:3])):
                    start_t = standard_timings[t_idx]
                    existing_show = shows_coll.find_one({
                        "movie_id": m_id,
                        "cinema_id": c_id,
                        "screen_id": str(screen["_id"]),
                        "date": target_date,
                        "start_time": start_t,
                    })

                    if not existing_show:
                        shows_coll.insert_one({
                            "movie_id": m_id,
                            "cinema_id": c_id,
                            "screen_id": str(screen["_id"]),
                            "date": target_date,
                            "start_time": start_t,
                            "end_time": "02:30 hours later",
                            "price_tiers": {
                                "VIP": 550.0,
                                "Platinum": 380.0,
                                "Gold": 250.0,
                                "Silver": 180.0,
                            },
                            "status": "scheduled",
                            "created_at": now(),
                            "updated_at": now(),
                        })
                        shows_count += 1

    print(f"Seeded {shows_count} scheduled showtimes across all cities.")

    # 4. Seed Coupons
    coupons_coll = get_coupons_collection()
    for cp in COUPONS_DATA:
        existing_cp = coupons_coll.find_one({"code": cp["code"]})
        if not existing_cp:
            cp_doc = dict(cp)
            cp_doc["usage_limit"] = 5000
            cp_doc["times_used"] = 12
            cp_doc["created_at"] = now()
            coupons_coll.insert_one(cp_doc)

    print(f"Seeded {len(COUPONS_DATA)} promotional discount coupons.")

    # 5. Seed Cinema Snacks
    snacks_coll = get_snacks_collection()
    for snk in SNACKS_DATA:
        existing_snk = snacks_coll.find_one({"id": snk["id"]})
        if not existing_snk:
            snk_doc = dict(snk)
            snk_doc["created_at"] = now()
            snacks_coll.insert_one(snk_doc)

    print(f"Seeded cinema gourmet snacks and beverages.")

    # 6. Seed Admin Account
    users_coll = get_users_collection()
    admin_email = Config.ADMIN_EMAIL.lower()
    existing_admin = users_coll.find_one({"email": admin_email})
    admin_hash = generate_password_hash(Config.ADMIN_PASSWORD, method="pbkdf2:sha256")

    if not existing_admin:
        users_coll.insert_one({
            "name": "Cinepass Administrator",
            "email": admin_email,
            "password_hash": admin_hash,
            "phone": "+91 9999999999",
            "role": "admin",
            "preferences": {"favorite_genres": ["Action", "Sci-Fi"], "preferred_city": "Mumbai"},
            "created_at": now(),
            "updated_at": now(),
        })
        print(f"Seeded default administrator account ({admin_email}).")
    else:
        users_coll.update_one({"email": admin_email}, {"$set": {"role": "admin", "password_hash": admin_hash}})

    print("Cinepass database seeding complete!")


if __name__ == "__main__":
    seed_all()
